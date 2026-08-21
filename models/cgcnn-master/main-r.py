import argparse
import os
import shutil
import sys
import time
import warnings
from random import sample

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn import metrics
from torch.autograd import Variable
from torch.optim.lr_scheduler import MultiStepLR
from torch.utils.data import DataLoader

from cgcnn.data import CIFData
from cgcnn.data import collate_pool, get_train_val_test_loader
from cgcnn.model import CrystalGraphConvNet


parser = argparse.ArgumentParser(description='Crystal Graph Convolutional Neural Networks')
parser.add_argument('data_options', metavar='OPTIONS', nargs='+',
                    help='dataset options, started with the path to root dir, then other options')
parser.add_argument('--task', choices=['regression', 'classification'],
                    default='regression',
                    help='complete a regression or classification task (default: regression)')
parser.add_argument('--split-mode', choices=['auto', 'manual'], default='auto',
                    help='split mode: auto uses id_prop.csv and ratio split, manual uses train/val/test csv files')
parser.add_argument('--disable-cuda', action='store_true',
                    help='Disable CUDA')
parser.add_argument('-j', '--workers', default=0, type=int, metavar='N',
                    help='number of data loading workers (default: 0)')
parser.add_argument('--epochs', default=30, type=int, metavar='N',
                    help='number of total epochs to run (default: 30)')
parser.add_argument('--start-epoch', default=0, type=int, metavar='N',
                    help='manual epoch number (useful on restarts)')
parser.add_argument('-b', '--batch-size', default=256, type=int,
                    metavar='N', help='mini-batch size (default: 256)')
parser.add_argument('--lr', '--learning-rate', default=0.01, type=float,
                    metavar='LR', help='initial learning rate (default: 0.01)')
parser.add_argument('--lr-milestones', default=[100], nargs='+', type=int,
                    metavar='N', help='milestones for scheduler (default: [100])')
parser.add_argument('--momentum', default=0.9, type=float, metavar='M',
                    help='momentum')
parser.add_argument('--weight-decay', '--wd', default=0, type=float,
                    metavar='W', help='weight decay (default: 0)')
parser.add_argument('--print-freq', '-p', default=10, type=int,
                    metavar='N', help='print frequency (default: 10)')
parser.add_argument('--resume', default='', type=str, metavar='PATH',
                    help='path to latest checkpoint (default: none)')

train_group = parser.add_mutually_exclusive_group()
train_group.add_argument('--train-ratio', default=None, type=float, metavar='N',
                         help='number of training data to be loaded (default none)')
train_group.add_argument('--train-size', default=None, type=int, metavar='N',
                         help='number of training data to be loaded (default none)')

valid_group = parser.add_mutually_exclusive_group()
valid_group.add_argument('--val-ratio', default=0.1, type=float, metavar='N',
                         help='percentage of validation data to be loaded (default 0.1)')
valid_group.add_argument('--val-size', default=None, type=int, metavar='N',
                         help='number of validation data to be loaded (default 1000)')

test_group = parser.add_mutually_exclusive_group()
test_group.add_argument('--test-ratio', default=0.1, type=float, metavar='N',
                        help='percentage of test data to be loaded (default 0.1)')
test_group.add_argument('--test-size', default=None, type=int,
                        metavar='N', help='number of test data to be loaded (default 1000)')

parser.add_argument('--optim', default='SGD', type=str, metavar='SGD',
                    help='choose an optimizer, SGD or Adam, (default: SGD)')
parser.add_argument('--atom-fea-len', default=64, type=int, metavar='N',
                    help='number of hidden atom features in conv layers')
parser.add_argument('--h-fea-len', default=128, type=int, metavar='N',
                    help='number of hidden features after pooling')
parser.add_argument('--n-conv', default=3, type=int, metavar='N',
                    help='number of conv layers')
parser.add_argument('--n-h', default=1, type=int, metavar='N',
                    help='number of hidden layers after pooling')

parser.add_argument('--radius', default=8.0, type=float, metavar='N',
                    help='neighbor search radius for crystal graph (default: 8.0 \u00c5)')
parser.add_argument('--max-num-nbr', default=12, type=int, metavar='N',
                    help='max number of neighbors for each atom (default: 12)')

parser.add_argument('--train-file', default=None, type=str,
                    help='training csv file for manual split mode')
parser.add_argument('--val-file', default=None, type=str,
                    help='validation csv file for manual split mode')
parser.add_argument('--test-file', default=None, type=str,
                    help='test csv file for manual split mode')

args = parser.parse_args(sys.argv[1:])

args.cuda = not args.disable_cuda and torch.cuda.is_available()

if args.task == 'regression':
    best_mae_error = 1e10
else:
    best_mae_error = 0.


def resolve_split_path(root_dir, split_file):
    if split_file is None:
        return None
    if os.path.isabs(split_file):
        return split_file
    return os.path.join(root_dir, split_file)


def main():
    global args, best_mae_error

    root_dir = args.data_options[0]
    collate_fn = collate_pool

    use_manual_split = (
        args.split_mode == 'manual'
        or args.train_file is not None
        or args.val_file is not None
        or args.test_file is not None
    )

    if use_manual_split:
        if not (args.train_file and args.val_file and args.test_file):
            raise ValueError(
                'In manual split mode, you must provide --train-file, --val-file and --test-file together.'
            )

        print('=> Using manual split mode')
        print('   train file: {}'.format(args.train_file))
        print('   val file:   {}'.format(args.val_file))
        print('   test file:  {}'.format(args.test_file))

        train_file = resolve_split_path(root_dir, args.train_file)
        val_file = resolve_split_path(root_dir, args.val_file)
        test_file = resolve_split_path(root_dir, args.test_file)

        train_dataset = CIFData(root_dir,
                                radius=args.radius,
                                max_num_nbr=args.max_num_nbr,
                                id_prop_file=train_file,
                                shuffle=True)

        val_dataset = CIFData(root_dir,
                              radius=args.radius,
                              max_num_nbr=args.max_num_nbr,
                              id_prop_file=val_file,
                              shuffle=False)

        test_dataset = CIFData(root_dir,
                               radius=args.radius,
                               max_num_nbr=args.max_num_nbr,
                               id_prop_file=test_file,
                               shuffle=False)

        train_loader = DataLoader(train_dataset,
                                  batch_size=args.batch_size,
                                  shuffle=True,
                                  num_workers=args.workers,
                                  collate_fn=collate_fn,
                                  pin_memory=args.cuda)

        val_loader = DataLoader(val_dataset,
                                batch_size=args.batch_size,
                                shuffle=False,
                                num_workers=args.workers,
                                collate_fn=collate_fn,
                                pin_memory=args.cuda)

        test_loader = DataLoader(test_dataset,
                                 batch_size=args.batch_size,
                                 shuffle=False,
                                 num_workers=args.workers,
                                 collate_fn=collate_fn,
                                 pin_memory=args.cuda)

        dataset_for_stats = train_dataset

    else:
        print('=> Using default id_prop.csv + automatic split mode')

        dataset = CIFData(root_dir,
                          radius=args.radius,
                          max_num_nbr=args.max_num_nbr,
                          id_prop_file='id_prop.csv',
                          shuffle=True)

        train_loader, val_loader, test_loader = get_train_val_test_loader(
            dataset=dataset,
            collate_fn=collate_fn,
            batch_size=args.batch_size,
            train_ratio=args.train_ratio,
            num_workers=args.workers,
            val_ratio=args.val_ratio,
            test_ratio=args.test_ratio,
            pin_memory=args.cuda,
            train_size=args.train_size,
            val_size=args.val_size,
            test_size=args.test_size,
            return_test=True)

        dataset_for_stats = dataset

    if args.task == 'classification':
        normalizer = Normalizer(torch.zeros(2))
        normalizer.load_state_dict({'mean': 0., 'std': 1.})
    else:
        if len(dataset_for_stats) < 500:
            warnings.warn('Dataset has less than 500 data points. Lower accuracy is expected.')
            sample_data_list = [dataset_for_stats[i] for i in range(len(dataset_for_stats))]
        else:
            sample_data_list = [dataset_for_stats[i] for i in
                                sample(range(len(dataset_for_stats)), 500)]
        _, sample_target, _ = collate_pool(sample_data_list)
        normalizer = Normalizer(sample_target)

    structures, _, _ = dataset_for_stats[0]
    orig_atom_fea_len = structures[0].shape[-1]
    nbr_fea_len = structures[1].shape[-1]

    model = CrystalGraphConvNet(
        orig_atom_fea_len,
        nbr_fea_len,
        atom_fea_len=args.atom_fea_len,
        n_conv=args.n_conv,
        h_fea_len=args.h_fea_len,
        n_h=args.n_h,
        classification=True if args.task == 'classification' else False
    )
    if args.cuda:
        model.cuda()

    if args.task == 'classification':
        class_weights = torch.tensor([1.0, 3.0], dtype=torch.float)
        if args.cuda:
            class_weights = class_weights.cuda()
        criterion = nn.NLLLoss(weight=class_weights)
        print('=> Using weighted NLLLoss for classification')
        print('   class weights: [1.0, 3.0]')
    else:
        criterion = nn.MSELoss()

    if args.optim == 'SGD':
        optimizer = optim.SGD(model.parameters(), args.lr,
                              momentum=args.momentum,
                              weight_decay=args.weight_decay)
    elif args.optim == 'Adam':
        optimizer = optim.Adam(model.parameters(), args.lr,
                               weight_decay=args.weight_decay)
    else:
        raise NameError('Only SGD or Adam is allowed as --optim')

    if args.resume:
        if os.path.isfile(args.resume):
            print("=> loading checkpoint '{}'".format(args.resume))
            checkpoint = torch.load(args.resume, map_location='')
            args.start_epoch = checkpoint['epoch']
            best_mae_error = checkpoint['best_mae_error']
            model.load_state_dict(checkpoint['state_dict'])
            optimizer.load_state_dict(checkpoint['optimizer'])
            normalizer.load_state_dict(checkpoint['normalizer'])
            print("=> loaded checkpoint '{}' (epoch {})"
                  .format(args.resume, checkpoint['epoch']))
        else:
            print("=> no checkpoint found at '{}'".format(args.resume))

    scheduler = MultiStepLR(optimizer, milestones=args.lr_milestones, gamma=0.1)

    for epoch in range(args.start_epoch, args.epochs):
        train(train_loader, model, criterion, optimizer, epoch, normalizer)

        metric_value = validate(val_loader, model, criterion, normalizer)

        if metric_value != metric_value:
            print('Exit due to NaN')
            sys.exit(1)

        scheduler.step()

        if args.task == 'regression':
            is_best = metric_value < best_mae_error
            best_mae_error = min(metric_value, best_mae_error)
        else:
            is_best = metric_value > best_mae_error
            best_mae_error = max(metric_value, best_mae_error)

        save_checkpoint({
            'epoch': epoch + 1,
            'state_dict': model.state_dict(),
            'best_mae_error': best_mae_error,
            'optimizer': optimizer.state_dict(),
            'normalizer': normalizer.state_dict(),
            'args': vars(args)
        }, is_best)

    print('---------训练完成，加载最优模型评估测试集---------------')
    best_checkpoint = torch.load('model_best.pth.tar', map_location='cpu')
    model.load_state_dict(best_checkpoint['state_dict'])
    validate(test_loader, model, criterion, normalizer, test=True)


def train(train_loader, model, criterion, optimizer, epoch, normalizer):
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()

    if args.task == 'regression':
        mae_errors = AverageMeter()
    else:
        accuracies = AverageMeter()
        precisions = AverageMeter()
        recalls = AverageMeter()
        fscores = AverageMeter()
        auc_scores = AverageMeter()

    model.train()

    end = time.time()
    for i, (input, target, _) in enumerate(train_loader):
        data_time.update(time.time() - end)

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

        if args.task == 'regression':
            target_normed = normalizer.norm(target)
        else:
            target_normed = target.view(-1).long()

        if args.cuda:
            target_var = Variable(target_normed.cuda(non_blocking=True))
        else:
            target_var = Variable(target_normed)

        output = model(*input_var)
        loss = criterion(output, target_var)

        if args.task == 'regression':
            mae_error = mae(normalizer.denorm(output.data.cpu()), target)
            losses.update(loss.data.cpu().item(), target.size(0))
            mae_errors.update(mae_error.item(), target.size(0))
        else:
            accuracy, precision, recall, fscore, auc_score = class_eval(output.data.cpu(), target)
            losses.update(loss.data.cpu().item(), target.size(0))
            accuracies.update(accuracy, target.size(0))
            precisions.update(precision, target.size(0))
            recalls.update(recall, target.size(0))
            fscores.update(fscore, target.size(0))

            if not np.isnan(auc_score):
                auc_scores.update(auc_score, target.size(0))

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0:
            if args.task == 'regression':
                print('Epoch: [{0}][{1}/{2}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'MAE {mae_errors.val:.3f} ({mae_errors.avg:.3f})'.format(
                    epoch, i, len(train_loader), batch_time=batch_time,
                    data_time=data_time, loss=losses, mae_errors=mae_errors))
            else:
                auc_val_str = '{:.3f}'.format(auc_scores.val) if auc_scores.count > 0 else 'nan'
                auc_avg_str = '{:.3f}'.format(auc_scores.avg) if auc_scores.count > 0 else 'nan'

                print('Epoch: [{0}][{1}/{2}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'Accu {accu.val:.3f} ({accu.avg:.3f})\t'
                      'Precision {prec.val:.3f} ({prec.avg:.3f})\t'
                      'Recall {recall.val:.3f} ({recall.avg:.3f})\t'
                      'F1 {f1.val:.3f} ({f1.avg:.3f})\t'
                      'AUC {auc_val} ({auc_avg})'.format(
                    epoch, i, len(train_loader), batch_time=batch_time,
                    data_time=data_time, loss=losses, accu=accuracies,
                    prec=precisions, recall=recalls, f1=fscores,
                    auc_val=auc_val_str, auc_avg=auc_avg_str))


def validate(val_loader, model, criterion, normalizer, test=False):
    batch_time = AverageMeter()
    losses = AverageMeter()

    if args.task == 'regression':
        mae_errors = AverageMeter()
    else:
        accuracies = AverageMeter()
        precisions = AverageMeter()
        recalls = AverageMeter()
        fscores = AverageMeter()

        all_targets = []
        all_scores = []

    if test:
        test_targets = []
        test_probs = []
        test_preds = []
        test_cif_ids = []

    model.eval()

    end = time.time()

    for i, (input, target, batch_cif_ids) in enumerate(val_loader):
        if args.cuda:
            with torch.no_grad():
                input_var = (Variable(input[0].cuda(non_blocking=True)),
                             Variable(input[1].cuda(non_blocking=True)),
                             input[2].cuda(non_blocking=True),
                             [crys_idx.cuda(non_blocking=True) for crys_idx in input[3]])
        else:
            with torch.no_grad():
                input_var = (Variable(input[0]),
                             Variable(input[1]),
                             input[2],
                             input[3])

        if args.task == 'regression':
            target_normed = normalizer.norm(target)
        else:
            target_normed = target.view(-1).long()

        if args.cuda:
            with torch.no_grad():
                target_var = Variable(target_normed.cuda(non_blocking=True))
        else:
            with torch.no_grad():
                target_var = Variable(target_normed)

        with torch.no_grad():
            output = model(*input_var)
            loss = criterion(output, target_var)

        if args.task == 'regression':
            mae_error = mae(normalizer.denorm(output.data.cpu()), target)
            losses.update(loss.data.cpu().item(), target.size(0))
            mae_errors.update(mae_error.item(), target.size(0))

            if test:
                test_pred = normalizer.denorm(output.data.cpu())
                test_target = target
                test_preds += test_pred.view(-1).tolist()
                test_targets += test_target.view(-1).tolist()
                test_cif_ids += batch_cif_ids
        else:
            accuracy, precision, recall, fscore, batch_auc = class_eval(output.data.cpu(), target)

            losses.update(loss.data.cpu().item(), target.size(0))
            accuracies.update(accuracy, target.size(0))
            precisions.update(precision, target.size(0))
            recalls.update(recall, target.size(0))
            fscores.update(fscore, target.size(0))

            prob = torch.exp(output.data.cpu())[:, 1].numpy()
            pred_label = np.argmax(output.data.cpu().numpy(), axis=1)
            true = target.view(-1).cpu().numpy().astype(int)

            all_scores.extend(prob.tolist())
            all_targets.extend(true.tolist())

            if test:
                test_probs += prob.tolist()
                test_preds += pred_label.tolist()
                test_targets += true.tolist()
                test_cif_ids += batch_cif_ids

        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0:
            if args.task == 'regression':
                print('Test: [{0}/{1}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'MAE {mae_errors.val:.3f} ({mae_errors.avg:.3f})'.format(
                    i, len(val_loader), batch_time=batch_time, loss=losses,
                    mae_errors=mae_errors))
            else:
                if np.isnan(batch_auc):
                    batch_auc_str = 'nan'
                else:
                    batch_auc_str = '{:.3f}'.format(batch_auc)

                print('Test: [{0}/{1}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'Accu {accu.val:.3f} ({accu.avg:.3f})\t'
                      'Precision {prec.val:.3f} ({prec.avg:.3f})\t'
                      'Recall {recall.val:.3f} ({recall.avg:.3f})\t'
                      'F1 {f1.val:.3f} ({f1.avg:.3f})\t'
                      'BatchAUC {batch_auc}'.format(
                    i, len(val_loader), batch_time=batch_time, loss=losses,
                    accu=accuracies, prec=precisions, recall=recalls,
                    f1=fscores, batch_auc=batch_auc_str))

    if test:
        star_label = '**'
        import csv
        with open('test_results.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            if args.task == 'regression':
                writer.writerow(['CIF_ID', 'Target', 'Prediction'])
                for cif_id, target_item, pred_item in zip(
                        test_cif_ids, test_targets, test_preds):
                    writer.writerow([cif_id, float(target_item), float(pred_item)])
            else:
                writer.writerow(['cif_id', 'true_label', 'pred_prob', 'pred_label'])
                for cif_id, target_item, prob_item, pred_item in zip(
                        test_cif_ids, test_targets, test_probs, test_preds):
                    writer.writerow([cif_id, int(target_item), float(prob_item), int(pred_item)])
    else:
        star_label = '*'

    if args.task == 'regression':
        print(' {star} MAE {mae_errors.avg:.3f}'.format(
            star=star_label, mae_errors=mae_errors))
        return mae_errors.avg
    else:
        all_targets = np.array(all_targets)
        all_scores = np.array(all_scores)

        if len(np.unique(all_targets)) < 2:
            auc_all = np.nan
            print(' {star} AUC nan (only one class in whole set)'.format(star=star_label))
        else:
            auc_all = metrics.roc_auc_score(all_targets, all_scores)
            print(' {star} Accu {accu:.3f} Precision {prec:.3f} Recall {rec:.3f} F1 {f1:.3f} AUC {auc:.3f}'.format(
                star=star_label,
                accu=accuracies.avg,
                prec=precisions.avg,
                rec=recalls.avg,
                f1=fscores.avg,
                auc=auc_all
            ))

        return auc_all


class Normalizer(object):
    """Normalize a Tensor and restore it later."""

    def __init__(self, tensor):
        self.mean = torch.mean(tensor)
        self.std = torch.std(tensor)
        if self.std.item() == 0:
            self.std = torch.tensor(1.0, dtype=tensor.dtype, device=tensor.device)

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
    return torch.mean(torch.abs(target - prediction))


def class_eval(prediction, target):
    """
    单个 batch 的分类评估。
    如果当前 batch 的真实标签只有一个类别，则 batch AUC 返回 np.nan。
    最终验证集/测试集 AUC 应在 validate() 中基于整个集合统一计算。
    """
    prediction = np.exp(prediction.numpy())
    target = target.numpy()

    pred_label = np.argmax(prediction, axis=1)
    target_label = np.squeeze(target).astype(int)

    if not target_label.shape:
        target_label = np.asarray([target_label])

    if prediction.shape[1] == 2:
        accuracy = metrics.accuracy_score(target_label, pred_label)
        precision, recall, fscore, _ = metrics.precision_recall_fscore_support(
            target_label,
            pred_label,
            average='binary',
            zero_division=0
        )

        if len(np.unique(target_label)) < 2:
            auc_score = np.nan
        else:
            auc_score = metrics.roc_auc_score(target_label, prediction[:, 1])
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


def adjust_learning_rate(optimizer, epoch, k):
    assert type(k) is int
    lr = args.lr * (0.1 ** (epoch // k))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


if __name__ == '__main__':
    main()
