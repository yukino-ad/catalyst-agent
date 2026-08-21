#!/bin/bash
#SBATCH -J Cluster188_POSCAR_Cu_HEA_FCC_0136_Co6_Cu8_Fe6_Ni6_Ti6_ID50249003.vasp_Sorted
#SBATCH -N 1
#SBATCH --ntasks-per-node=32
#SBATCH -p xahcnormal

module purge
source /work/home/chenheli/apprepo/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc/scripts/env.sh

export MKL_DEBUG_CPU_TYPE=5
export MKL_CBWR=AVX2
export I_MPI_PIN_DOMAIN=numa

srun --mpi=pmi2 vasp_std
