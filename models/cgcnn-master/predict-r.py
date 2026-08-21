import argparse
import os
import shutil
import sys
import time

import numpy as np
import torch
import torch.nn as nn
from sklearn import metrics
from torch.autograd import Variable
from torch.utils.data import DataLoader

from cgcnn.data import CIFData
from cgcnn.data import collate_pool
from cgcnn.model import CrystalGraphConvNet

parser = argparse.ArgumentParser(description='Crystal gated neural networks')
parser.add_argument('modelpath', help='path to the trained model.')
parser.add_argument('cifpath', help='path to the directory of CIF files.')
parser.add_argument('-b', '--batch-size', default=256, type=int,
                    metavar='N', help='mini-batch size (default: 256)')
parser.add_argument('-j', '--workers', default=0, type=int, metavar='N',
                    help='number of data loading workers (default: 0)')
parser.add_argument('--disable-cuda', action='store_true',
                    help='Disable CUDA')
parser.add_argument('--print-freq', '-p', default=10, type=int,
                    metavar='N', help='print frequency (default: 10)')
# 保留参数定义，但实际会从预训练模型中读取，保证和训练一致
parser.add_argument('--radius', default=8.0, type=float, metavar='N',
                    help='neighbor search radius for crystal graph (default: 8.0 Å)')
parser.add_argument('--max-num-nbr', default=12, type=int, metavar='N',
                    help='max number of neighbors for each atom (default: 12)')

args = parser.parse_args(sys.argv[1:])

# 加载预训练模型的checkpoint，优先读取训练时的参数
if os.path.isfile(args.modelpath):
    print("=> loading model params '{}'".format(args.modelpath))
    model_checkpoint = torch.load(args.modelpath,
                                  map_location=lambda storage, loc: storage,
                                  weights_only=False)
    # 从checkpoint中读取训练时的参数，覆盖命令行默认值
    model_args = argparse.Namespace(**model_checkpoint['args'])
    # 关键：用训练时的radius/max_num_nbr，保证晶体图维度一致
    args.radius = model_args.radius if hasattr(model_args, 'radius') else args.radius
    args.max_num_nbr = model_args.max_num_nbr if hasattr(model_args, 'max_num_nbr') else args.max_num_nbr
    print("=> loaded model params '{}'".format(args.modelpath))
    print(f"=> using training params: radius={args.radius}, max_num_nbr={args.max_num_nbr}")
else:
    print("=> no model params found at '{}'".format(args.modelpath))
    sys.exit(1)

args.cuda = not args.disable_cuda and torch.cuda.is_available()

# 初始化最优指标
if model_args.task == 'regression':
    best_mae_error = 1e10
else:
    best_mae_error = 0.


def main():
    global args, model_args, best_mae_error

    # 加载数据：使用训练时的radius/max_num_nbr，保证晶体图特征维度一致
    print(f"=> loading CIF data with radius={args.radius}, max_num_nbr={args.max_num_nbr}")
    dataset = CIFData(args.cifpath, radius=args.radius, max_num_nbr=args.max_num_nbr)
    collate_fn = collate_pool
    test_loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True,
                             num_workers=args.workers, collate_fn=collate_fn,
                             pin_memory=args.cuda)

    # 构建模型：使用checkpoint中的模型参数，保证结构完全一致
    structures, _, _ = dataset[0]
    orig_atom_fea_len = structures[0].shape[-1]
    nbr_fea_len = structures[1].shape[-1]
    model = CrystalGraphConvNet(orig_atom_fea_len, nbr_fea_len,
                                atom_fea_len=model_args.atom_fea_len,
                                n_conv=model_args.n_conv,
                                h_fea_len=model_args.h_fea_len,
                                n_h=model_args.n_h,
                                classification=True if model_args.task == 'classification' else False)
    if args.cuda:
        model.cuda()
    print(f"=> model built with orig_atom_fea_len={orig_atom_fea_len}, nbr_fea_len={nbr_fea_len}")

    # 定义损失函数
    if model_args.task == 'classification':
        criterion = nn.NLLLoss()
    else:
        criterion = nn.MSELoss()

    # 加载Normalizer：从checkpoint读取，而非默认零张量（关键修复）
    normalizer = Normalizer(torch.zeros(1))  # 占位，后续从checkpoint加载
    if os.path.isfile(args.modelpath):
        print("=> loading model '{}'".format(args.modelpath))
        checkpoint = torch.load(args.modelpath,
                                map_location=lambda storage, loc: storage,
                                weights_only=False)
        # 加载模型权重：添加strict=False兼容微小参数不匹配
        try:
            model.load_state_dict(checkpoint['state_dict'])
            print("=> loaded model weights with exact match")
        except RuntimeError as e:
            print(f"=> exact weight match failed: {e}")
            print("=> trying to load weights with strict=False (ignore minor mismatches)")
            model.load_state_dict(checkpoint['state_dict'], strict=False)
        # 加载训练时的Normalizer参数（核心）
        normalizer.load_state_dict(checkpoint['normalizer'])
        print("=> loaded normalizer from checkpoint (mean={:.4f}, std={:.4f})"
              .format(normalizer.mean.item(), normalizer.std.item()))
        print("=> loaded model '{}' (epoch {}, validation {})"
              .format(args.modelpath, checkpoint['epoch'], checkpoint['best_mae_error']))
    else:
        print("=> no model found at '{}'".format(args.modelpath))
        sys.exit(1)

    # 执行验证/预测
    validate(test_loader, model, criterion, normalizer, test=True)


def validate(val_loader, model, criterion, normalizer, test=False):
    batch_time = AverageMeter()
    losses = AverageMeter()
    if model_args.task == 'regression':
        mae_errors = AverageMeter()
    else:
        accuracies = AverageMeter()
        precisions = AverageMeter()
        recalls = AverageMeter()
        fscores = AverageMeter()
        auc_scores = AverageMeter()
    if test:
        test_targets = []
        test_preds = []
        test_cif_ids = []

    # 切换到评估模式
    model.eval()

    end = time.time()
    for i, (input, target, batch_cif_ids) in enumerate(val_loader):
        with torch.no_grad():
            if args.cuda:
                input_var = (Variable(input[0].cuda(non_blocking=True)),
                             Variable(input[1].cuda(non_blocking=True)),
                             input[2].cuda(non_blocking=True),
                             [crys_idx.cuda(non_blocking=True) for crys_idx in input[3]])
            else:
                input_var = (Variable(input[0]),
                             Variable(input[1]),
                             input[2],
                             input[3])
        if model_args.task == 'regression':
            target_normed = normalizer.norm(target)
        else:
            target_normed = target.view(-1).long()
        with torch.no_grad():
            if args.cuda:
                target_var = Variable(target_normed.cuda(non_blocking=True))
            else:
                target_var = Variable(target_normed)

        # 计算预测输出
        output = model(*input_var)
        loss = criterion(output, target_var)

        # 计算指标
        if model_args.task == 'regression':
            mae_error = mae(normalizer.denorm(output.data.cpu()), target)
            losses.update(loss.data.cpu().item(), target.size(0))
            mae_errors.update(mae_error, target.size(0))
            if test:
                test_pred = normalizer.denorm(output.data.cpu())
                test_target = target
                test_preds += test_pred.view(-1).tolist()
                test_targets += test_target.view(-1).tolist()
                test_cif_ids += batch_cif_ids
        else:
            accuracy, precision, recall, fscore, auc_score = class_eval(output.data.cpu(), target)
            losses.update(loss.data.cpu().item(), target.size(0))
            accuracies.update(accuracy, target.size(0))
            precisions.update(precision, target.size(0))
            recalls.update(recall, target.size(0))
            fscores.update(fscore, target.size(0))
            auc_scores.update(auc_score, target.size(0))
            if test:
                test_pred = torch.exp(output.data.cpu())
                test_target = target
                assert test_pred.shape[1] == 2
                test_preds += test_pred[:, 1].tolist()
                test_targets += test_target.view(-1).tolist()
                test_cif_ids += batch_cif_ids

        # 统计耗时
        batch_time.update(time.time() - end)
        end = time.time()

        # 打印进度
        if i % args.print_freq == 0:
            if model_args.task == 'regression':
                print('Test: [{0}/{1}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'MAE {mae_errors.val:.3f} ({mae_errors.avg:.3f})'.format(
                       i, len(val_loader), batch_time=batch_time, loss=losses,
                       mae_errors=mae_errors))
            else:
                print('Test: [{0}/{1}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'Accu {accu.val:.3f} ({accu.avg:.3f})\t'
                      'Precision {prec.val:.3f} ({prec.avg:.3f})\t'
                      'Recall {recall.val:.3f} ({recall.avg:.3f})\t'
                      'F1 {f1.val:.3f} ({f1.avg:.3f})\t'
                      'AUC {auc.val:.3f} ({auc.avg:.3f})'.format(
                       i, len(val_loader), batch_time=batch_time, loss=losses,
                       accu=accuracies, prec=precisions, recall=recalls,
                       f1=fscores, auc=auc_scores))

    # 保存预测结果到CSV
    if test:
        star_label = '**'
        # 保存结果到test_results.csv，路径改为当前目录
        csv_path = os.path.join(os.getcwd(), 'test_results.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['CIF_ID', 'Target', 'Prediction'])  # 添加表头，更易读
            for cif_id, target, pred in zip(test_cif_ids, test_targets, test_preds):
                writer.writerow((cif_id, target, pred))
        print(f"=> prediction results saved to {csv_path}")
    else:
        star_label = '*'
    
    # 打印最终指标
    if model_args.task == 'regression':
        print(' {star} MAE {mae_errors.avg:.3f}'.format(star=star_label, mae_errors=mae_errors))
        return mae_errors.avg
    else:
        print(' {star} AUC {auc.avg:.3f}'.format(star=star_label, auc=auc_scores))
        return auc_scores.avg


class Normalizer(object):
    """Normalize a Tensor and restore it later. """
    def __init__(self, tensor):
        """tensor is taken as a sample to calculate the mean and std"""
        self.mean = torch.mean(tensor)
        self.std = torch.std(tensor)

    def norm(self, tensor):
        return (tensor - self.mean) / self.std

    def denorm(self, normed_tensor):
        return normed_tensor * self.std + self.mean

    def state_dict(self):
        return {'mean': self.mean, 'std': self.std}

    def load_state_dict(self, state_dict):
        self.mean = state_dict['mean']
        self.std = state_dict['std']


def mae(prediction, target):
    """Computes the mean absolute error between prediction and target"""
    return torch.mean(torch.abs(target - prediction))


def class_eval(prediction, target):
    prediction = np.exp(prediction.numpy())
    target = target.numpy()
    pred_label = np.argmax(prediction, axis=1)
    target_label = np.squeeze(target)
    if prediction.shape[1] == 2:
        precision, recall, fscore, _ = metrics.precision_recall_fscore_support(
            target_label, pred_label, average='binary')
        auc_score = metrics.roc_auc_score(target_label, prediction[:, 1])
        accuracy = metrics.accuracy_score(target_label, pred_label)
    else:
        raise NotImplementedError
    return accuracy, precision, recall, fscore, auc_score


class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    torch.save(state, filename)
    if is_best:
        shutil.copyfile(filename, 'model_best.pth.tar')


if __name__ == '__main__':
    # 补充导入csv模块（原代码遗漏）
    import csv
    main()