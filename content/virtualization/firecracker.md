Title:  Fircracker
Date: 2019-6-26 23:00
Modified: 2019-6-26 23:00
Tags: firecracker
Slug: firecracker
Status: draft
Authors: Yori Fang
Summary: AWS Firecracker


```
main =>  server = ApiServer::new() => server.bind_and_run() => service = ApiServerHttpService::new()
=> server::Service() => fn call() => match parse_request() => match path_tokens[0] => parse_actions_req()
=> IntoParsedRequest 
  => VmmAction::StartMicroVm => Vmm::send_response(self.start_microvm(), sender) => fn start_microvm(&mut self)

start_microvm
  =>  check_health        // check if kernel is none
  =>  init_guest_memory   // do memory init, get mem_size, GuestMemory
  == x86 ==
  =>  self.setup_interrupt_controller()?;
  =>  self.attach_virtio_devices()?;
  =>  self.attach_legacy_devices()?;
  =>  let entry_addr = self.load_kernel()?;
  =>  vcpus = self.create_vcpus(entry_addr, request_ts)?;
  =>  self.configure_system()?;
  =>  self.register_events()?;
  =>  self.start_vcpus(vcpus)?;
```

virtio设备activate的流程：
Guest Driver读写配置空间 -> fn write (BusDevice for MmioDevice) ->  0x70 => self.set_device_status(v)

