! SPDX-License-Identifier: MIT
! Copyright (c) 2020-2022 Advanced Micro Devices, Inc. All rights reserved.
module gpufortrt_core
  use iso_c_binding
  use gpufortrt_types

  public

  interface
    subroutine gpufortrt_init() bind(c,name="gpufortrt_init")
      implicit none
    end subroutine
  
    subroutine gpufortrt_shutdown() bind(c,name="gpufortrt_shutdown")
      implicit none
    end subroutine
  
    function gpufortrt_get_stream(async_arg) &
        bind(c,name="gpufortrt_get_stream") &
          result(stream)
      implicit none
      integer(gpufortrt_handle_kind),value,intent(in) :: async_arg
      !
      type(c_ptr) :: stream
    end function
  end interface

contains
  
  !> Ignore the result of a mapping routine.
  !> \param[in] deviceptr a device pointer.
  subroutine gpufortrt_ignore(deviceptr)
    type(c_ptr),intent(in) :: deviceptr
    ! nop
  end subroutine

  subroutine gpufortrt_wait(wait_arg,async_arg,condition)
    use iso_c_binding
    use hipfort
    use hipfort_check
    implicit none
    integer(gpufortrt_handle_kind),target,dimension(:),intent(in),optional :: wait_arg,async_arg
    logical,intent(in),optional                                            :: condition
    !
    interface
      subroutine gpufortrt_wait_all_c_impl(condition) &
          bind(c,name="gpufortrt_wait_all")
        implicit none
        logical(c_bool) :: condition 
      end subroutine
      subroutine gpufortrt_wait_all_async_c_impl(async_arg,num_async_args,condition) &
          bind(c,name="gpufortrt_wait_all_async")
        implicit none
        type(c_ptr) :: async_arg
        integer(c_int) :: num_async_args
        logical(c_bool) :: condition 
      end subroutine
      subroutine gpufortrt_wait_c_impl(wait_arg,num_wait_args,condition) &
          bind(c,name="gpufortrt_wait_async")
        implicit none
        type(c_ptr) :: wait_arg
        integer(c_int) :: num_wait_args
        logical(c_bool) :: condition 
      end subroutine
      subroutine gpufortrt_wait_async_c_impl(wait_arg,num_wait_args,&
                                             async_arg,num_async_args,&
                                             condition) &
          bind(c,name="gpufortrt_wait_async")
        implicit none
        type(c_ptr) :: wait_arg, async_arg
        integer(c_int) :: num_wait_args, num_async_args
        logical(c_bool) :: condition 
      end subroutine
    end interface
    !
    if ( present(wait_arg) ) then
      if ( present(async_arg) ) then
        call gpufortrt_wait_async_c_impl(&
             c_loc(wait_arg),size(wait_arg,kind=c_int),&
             c_loc(async_arg),size(async_arg,kind=c_int),&
             logical(eval_optval(condition,.true.),c_bool))
      else
        call gpufortrt_wait_c_impl(&
             c_loc(wait_arg),size(wait_arg,kind=c_int),&
             logical(eval_optval(condition,.true.),c_bool))
      endif
    else
      if ( present(async_arg) ) then
        call gpufortrt_wait_all_async_c_impl(&
             c_loc(async_arg),size(async_arg,kind=c_int),&
             logical(eval_optval(condition,.true.),c_bool))
      else
        call gpufortrt_wait_all_c_impl(logical(eval_optval(condition,.true.),c_bool))
      endif
    endif
  end subroutine

  subroutine gpufortrt_data_start(mappings,async_arg)
  !subroutine gpufortrt_data_start(device_kind,mappings,async_arg)
    use iso_c_binding
    use openacc
    implicit none
    !integer,intent(in) :: device_kind
    type(mapping_t),dimension(:),intent(in),optional :: mappings
    integer(gpufortrt_handle_kind),intent(in),optional :: async_arg
    !
    interface
      subroutine gpufortrt_data_start_c_impl(mappings,num_mappings) bind(c,name="gpufortrt_data_start")
        use iso_c_binding
        implicit none
        type(c_ptr),intent(in),value :: mappings
        integer(c_int),intent(in),value :: num_mappings
      end subroutine
      subroutine gpufortrt_data_start_async_c_impl(mappings,num_mappings,async_arg) bind(c,name="gpufortrt_data_start_async")
        use iso_c_binding
        implicit none
        type(c_ptr),intent(in),value :: mappings
        integer(c_int),intent(in),value :: num_mappings
        integer(c_int),intent(in),value :: async_arg
      end subroutine
    end interface 
    !
    if ( present(async_arg) ) then
      if ( present(mappings) ) then
        call gpufortrt_data_start_async_c_impl(c_loc(mappings),size(mappings),&
                                               int(async_arg,kind=c_int))
      else
        call gpufortrt_data_start_async_c_impl(c_null_ptr,0_c_int_t,&
                                               int(async_arg,kind=c_int)) 
      endif
    else
      if ( present(mappings) ) then
        call gpufortrt_data_start_c_impl(c_loc(mappings),size(mappings))  
      else
        call gpufortrt_data_start_c_impl(c_null_ptr,0_c_int_t)  
      endif
    endif
  end subroutine
   
  subroutine gpufortrt_data_end(async_arg) bind(c,name="gpufortrt_data_end")
    implicit none
    integer(gpufortrt_handle_kind),intent(in),optional :: async_arg
    !
    interface
      subroutine gpufortrt_data_end_c_impl() bind(c,name="gpufortrt_data_end")
        use iso_c_binding
        implicit none
      end subroutine
      subroutine gpufortrt_data_end_async_c_impl(async_arg) bind(c,name="gpufortrt_data_end_async")
        use iso_c_binding
        implicit none
        integer(c_int),intent(in),value :: async_arg
      end subroutine
    end interface 
    !
    if ( present(async_arg) ) then
      call gpufortrt_data_end_async_c_impl(async_arg)  
    else
      call gpufortrt_data_end_c_impl()  
    endif
  end subroutine

  subroutine gpufortrt_enter_exit_data(mappings,async,finalize)
    use iso_c_binding
    use gpufortrt_auxiliary
    implicit none
    !
    !integer,intent(in)                              :: device_kind
    type(mapping_t),dimension(:),intent(in),optional :: mappings
    integer,intent(in),optional                      :: async
    logical,intent(in),optional                      :: finalize
    !
    interface
      subroutine gpufortrt_enter_exit_data_c_impl(mappings,num_mappings,finalize) bind(c,name="gpufortrt_enter_exit_data")
        use iso_c_binding
        implicit none
        type(c_ptr),value,intent(in)    :: mappings
        integer(c_int),value,intent(in) :: num_mappings
        logical(c_bool),value,intent(in) :: finalize
      end subroutine
      subroutine gpufortrt_enter_exit_data_async_c_impl(mappings,num_mappings,async,finalize) bind(c,name="gpufortrt_enter_exit_data_async")
        use iso_c_binding
        implicit none
        type(c_ptr),value,intent(in)    :: mappings
        integer(c_int),value,intent(in) :: num_mappings
        integer(c_int),value,intent(in) :: async
        logical(c_bool),value,intent(in) :: finalize
      end subroutine
    end interface 
    !
    if ( present(async) ) then
      if ( present(mappings) ) then
        call gpufortrt_enter_exit_data_async_c_impl(&
          c_loc(mappings),&
          size(mappings,kind=c_int_t),&
          async,&
          logical(eval_optval(finalize,.false.),kind=c_bool)) 
      else
        call gpufortrt_enter_exit_data_async_c_impl(&
          c_null_ptr,&
          0_c_size_t,&
          async,&
          logical(eval_optval(finalize,.false.),kind=c_bool)) 
      endif
    else
      if ( present(mappings) ) then
        call gpufortrt_enter_exit_data_c_impl(&
          c_loc(mappings),&
          size(mappings,kind=c_int_t),&
          logical(eval_optval(finalize,.false.),kind=c_bool)) 
      else
        call gpufortrt_enter_exit_data_c_impl(&
          c_null_ptr,&
          0_c_int_t,&
          logical(eval_optval(finalize,.false.),kind=c_bool)) 
      endif
    endif
  end subroutine

  !> Lookup device pointer for given host pointer.
  !> \param[in] condition condition that must be met, otherwise host pointer is returned. Defaults to '.true.'.
  !> \param[in] if_present Only return device pointer if one could be found for the host pointer.
  !>                       otherwise host pointer is returned. Defaults to '.false.'.
  !> \note Returns a c_null_ptr if the host pointer is invalid, i.e. not C associated.
  function gpufortrt_use_device_b(hostptr,num_bytes,condition,if_present) result(resultptr)
    use iso_c_binding
    implicit none
    type(c_ptr),intent(in)       :: hostptr
    integer(c_size_t),intent(in) :: num_bytes
    logical,intent(in),optional  :: condition, if_present
    !
    type(c_ptr) :: resultptr
    !
    interface
      function gpufortrt_use_device_c_impl(hostptr,num_bytes,condition,if_present) &
          bind(c,name="gpufortrt_use_device") &
          result(deviceptr)
        type(c_ptr),value,intent(in)       :: hostptr
        integer(c_size_t),value,intent(in) :: num_bytes
        logical(c_bool),value,intent(in)   :: condition, if_present
      end function
    end interface
    resultptr = gpufortrt_use_device_c_impl(hostptr,num_bytes,&
        eval_optval(logical(condition,kind=c_bool),.false._c_bool),&
        eval_optval(logical(if_present,kind=c_bool).false._c_bool),&
  end function

  subroutine gpufortrt_delete_b(hostptr,finalize)
    use iso_c_binding
    implicit none
    type(c_ptr), intent(in)     :: hostptr
    logical,intent(in),optional :: finalize
    !
    interface
      subroutine gpufortrt_delete_c_impl(hostptr) &
          bind(c,name="gpufortrt_delete") result(deviceptr)
        type(c_ptr),value,intent(in) :: hostptr
      end subroutine
      subroutine gpufortrt_delete_finalize_c_impl(hostptr,finalize) &
          bind(c,name="gpufortrt_delete_finalize") result(deviceptr)
        type(c_ptr),value,intent(in) :: hostptr
        logical(c_bool),value,intent(in) :: finalize
      end subroutine
      subroutine gpufortrt_delete_async_c_impl(hostptr) &
          bind(c,name="gpufortrt_delete") result(deviceptr)
        type(c_ptr),value,intent(in) :: hostptr
      end subroutine
      subroutine gpufortrt_delete_finalize_async_c_impl(hostptr,finalize) &
          bind(c,name="gpufortrt_delete_finalize") result(deviceptr)
        type(c_ptr),value,intent(in) :: hostptr
        logical(c_bool),value,intent(in) :: finalize
      end subroutine
    end interface
  end subroutine

  function gpufortrt_present_b(hostptr,num_bytes,ctr_to_update) result(deviceptr)
    use iso_c_binding
    implicit none
    type(c_ptr),intent(in) :: hostptr
    integer(c_size_t),intent(in) :: num_bytes
    integer(kind(gpufortrt_counter_none)),optional,intent(in) :: ctr_to_update
    !
    type(c_ptr) :: deviceptr
    !
    interface
      function gpufortrt_present_c_impl(hostptr,num_bytes,ctr_to_update) &
          bind(c,name="gpufortrt_present") result(deviceptr)
        type(c_ptr),value,intent(in) :: hostptr
        integer(c_size_t),value,intent(in) :: num_bytes
        integer(kind(gpufortrt_counter_none)),value,intent(in) :: ctr_to_update
      end function
    end interface
    !
    deviceptr = gpufortrt_present_c_impl(hostptr,num_bytes,&
        eval_optval(ctr_to_update,gpufortrt_counter_none))
  end function
end module
