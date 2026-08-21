#!/bin/bash
#SBATCH -J c116-Cu8Ni6Fe6Au6Co6-fcc-01_bulk_formation
#SBATCH -N 1
#SBATCH --ntasks-per-node=32
#SBATCH -p xahcnormal

module purge
module load vasp-5.4.4-intelmpi2017_ioptcell

export MKL_DEBUG_CPU_TYPE=5
export MKL_CBWR=AVX2
export I_MPI_PIN_DOMAIN=numa

srun --mpi=pmi2 vasp_std
