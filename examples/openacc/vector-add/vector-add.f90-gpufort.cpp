// This file was generated by GPUFORT

#ifndef VECTOR_ADD_F90_GPUFORT_CPP
#define VECTOR_ADD_F90_GPUFORT_CPP

// BEGIN main_17 4a81a2

/**
   HIP C++ implementation of the function/loop body of:

     !$acc parallel loop present(x,y)
     do i = 1, N
       x(i) = 1
       y(i) = 2
     end do

*/

__global__ void  main_17(
    gpufort::array1<int> x,
    gpufort::array1<int> y,
    int n
){
  int i = 1 + (1)*(threadIdx.x + blockIdx.x * blockDim.x);
  if (loop_cond(i,n,1)) {
    x(i)=1;
    y(i)=2;
  }
}

// END main_17 4a81a2

// BEGIN main_23 173b19

/**
   HIP C++ implementation of the function/loop body of:

     !$acc parallel loop
     do i = 1, N
       y(i) = x(i) + y(i)
     end do

*/

__global__ void  main_23(
    gpufort::array1<int> y,
    gpufort::array1<int> x,
    int n
){
  int i = 1 + (1)*(threadIdx.x + blockIdx.x * blockDim.x);
  if (loop_cond(i,n,1)) {
    y(i)=(x(i)+y(i));
  }
}

// END main_23 173b19

// BEGIN main_17 4a81a2

extern "C" hipError_t launch_main_17_hip_(
    dim3& grid,
    dim3& block,
    int& sharedmem,
    hipStream_t& stream,
    bool& async,
    gpufort::array1<int>& x,
    gpufort::array1<int>& y,
    int& n) {
  hipError_t ierr = hipSuccess;
  hipLaunchKernelGGL((main_17), grid, block, sharedmem, stream, x,y,n);
  bool synchronize_stream = !async;
  #if defined(SYNCHRONIZE_DEVICE_ALL) || defined(SYNCHRONIZE_DEVICE_main_17)
  ierr = hipDeviceSynchronize();
  if ( ierr != hipSuccess ) return ierr;
  synchronize_stream = false;
  #elif defined(SYNCHRONIZE_ALL) || defined(SYNCHRONIZE_main_17)
  synchronize_stream = true;
  #endif
  if ( synchronize_stream ) { 
    ierr = hipStreamSynchronize(stream);
    if ( ierr != hipSuccess ) return ierr;
  }
  return ierr;
}

extern "C" hipError_t launch_main_17_hip_ps_(
    dim3& problem_size,
    dim3& block,
    int& sharedmem,
    hipStream_t& stream,
    bool& async,
    gpufort::array1<int>& x,
    gpufort::array1<int>& y,
    int& n) {
  hipError_t ierr = hipSuccess;
  dim3 grid(divideAndRoundUp(problem_size.x,block.x),
            divideAndRoundUp(problem_size.y,block.y),
            divideAndRoundUp(problem_size.z,block.z));   
  hipLaunchKernelGGL((main_17), grid, block, sharedmem, stream, x,y,n);
  bool synchronize_stream = !async;
  #if defined(SYNCHRONIZE_DEVICE_ALL) || defined(SYNCHRONIZE_DEVICE_main_17)
  ierr = hipDeviceSynchronize();
  if ( ierr != hipSuccess ) return ierr;
  synchronize_stream = false;
  #elif defined(SYNCHRONIZE_ALL) || defined(SYNCHRONIZE_main_17)
  synchronize_stream = true;
  #endif
  if ( synchronize_stream ) { 
    ierr = hipStreamSynchronize(stream);
    if ( ierr != hipSuccess ) return ierr;
  }
  return ierr;
}

// END main_17 4a81a2

// BEGIN main_23 173b19

extern "C" hipError_t launch_main_23_hip_(
    dim3& grid,
    dim3& block,
    int& sharedmem,
    hipStream_t& stream,
    bool& async,
    gpufort::array1<int>& y,
    gpufort::array1<int>& x,
    int& n) {
  hipError_t ierr = hipSuccess;
  hipLaunchKernelGGL((main_23), grid, block, sharedmem, stream, y,x,n);
  bool synchronize_stream = !async;
  #if defined(SYNCHRONIZE_DEVICE_ALL) || defined(SYNCHRONIZE_DEVICE_main_23)
  ierr = hipDeviceSynchronize();
  if ( ierr != hipSuccess ) return ierr;
  synchronize_stream = false;
  #elif defined(SYNCHRONIZE_ALL) || defined(SYNCHRONIZE_main_23)
  synchronize_stream = true;
  #endif
  if ( synchronize_stream ) { 
    ierr = hipStreamSynchronize(stream);
    if ( ierr != hipSuccess ) return ierr;
  }
  return ierr;
}

extern "C" hipError_t launch_main_23_hip_ps_(
    dim3& problem_size,
    dim3& block,
    int& sharedmem,
    hipStream_t& stream,
    bool& async,
    gpufort::array1<int>& y,
    gpufort::array1<int>& x,
    int& n) {
  hipError_t ierr = hipSuccess;
  dim3 grid(divideAndRoundUp(problem_size.x,block.x),
            divideAndRoundUp(problem_size.y,block.y),
            divideAndRoundUp(problem_size.z,block.z));   
  hipLaunchKernelGGL((main_23), grid, block, sharedmem, stream, y,x,n);
  bool synchronize_stream = !async;
  #if defined(SYNCHRONIZE_DEVICE_ALL) || defined(SYNCHRONIZE_DEVICE_main_23)
  ierr = hipDeviceSynchronize();
  if ( ierr != hipSuccess ) return ierr;
  synchronize_stream = false;
  #elif defined(SYNCHRONIZE_ALL) || defined(SYNCHRONIZE_main_23)
  synchronize_stream = true;
  #endif
  if ( synchronize_stream ) { 
    ierr = hipStreamSynchronize(stream);
    if ( ierr != hipSuccess ) return ierr;
  }
  return ierr;
}

// END main_23 173b19
#endif // VECTOR_ADD_F90_GPUFORT_CPP