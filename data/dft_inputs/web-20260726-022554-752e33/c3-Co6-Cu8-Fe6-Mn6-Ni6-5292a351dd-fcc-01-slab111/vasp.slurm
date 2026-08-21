#!/bin/bash
#SBATCH -J c3-Co6-Cu8-Fe6-Mn6-Ni6-5292a351dd-fcc-01-slab111
#SBATCH -N 1
#SBATCH --ntasks-per-node=32
#SBATCH -p xahcnormal

module purge
module load vasp-5.4.4-intelmpi2017_ioptcell

export MKL_DEBUG_CPU_TYPE=5
export MKL_CBWR=AVX2
export I_MPI_PIN_DOMAIN=numa

srun --mpi=pmi2 vasp_std
