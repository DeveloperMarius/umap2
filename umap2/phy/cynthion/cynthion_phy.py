from umap2.phy.iphy import PhyInterface
import platform
from umap2.core.usb_device import USBDevice, USBDeviceRequest

from typing           import List, Tuple
from cynthion import Cynthion
from cynthion.boards.cynthion_moondancer import CynthionMoondancer
from pygreat.classes.core import CoreAPI

from facedancer.types import USBDirection, DeviceSpeed
from facedancer.backends.moondancer import InterruptEvent
from facedancer.request import USBControlRequest

# Based on: MoondancerApp from .venv/lib/python3.12/site-packages/facedancer/backends/moondancer.py
# MoondancerApp is used by the facedancer USBDevice .venv/lib/python3.12/site-packages/facedancer/device.py

# CynthionPhy will be used by umap2 USBDevice umap2/core/usb_device.py






# Havily based on .venv/lib/python3.12/site-packages/facedancer/backends/moondancer.py aka MoondancerApp
class CynthionPhy(PhyInterface):
    # Notes: 
    # Facedaner setAdress will do:
    # request.acknowledge(blocking=True)
    # self.set_address(request.value)
    # 
    # We just self.ack_status_stage()
    # maybe it is required to set_address
    
    
    
    
    app_name = "Moondancer"

    # Number of supported USB endpoints.
    SUPPORTED_ENDPOINTS = 16
    
    
    
    device_speed             : DeviceSpeed = None
    device : CynthionMoondancer = None
    api: CoreAPI = None
    # 1 Create physical
    # for device
    #   device = self.load_device(device_name, phy)
    #   device.connect()
    #       phy.connect(device)
    #   device.run()
    #       phy.run()
    #   device.disconnect()
    #       phy.disconnect()
    #   phy.disconnect()
    
    def __init__(self, app):
        super(CynthionPhy, self).__init__(app, 'CynthionPhy')
        if platform.system() != 'Linux':
            raise Exception('CynthionPhy is only supported on Linux')
        
        
        if not self.appropriate_for_environment('cynthion'):
            raise Exception('CynthionPhy is not supported on this platform')
        
        self.device = Cynthion()
        
        # CynthionMoondancer is a subclass of CynthionBoard which is a subclass of GreatBoard
        self.api = self.device.apis.moondancer

        # Initialize a dictionary that will store the last setup
        # whether each endpoint is currently stalled.
        self.endpoint_stalled = {}
        for i in range(self.SUPPORTED_ENDPOINTS):
            self.endpoint_stalled[i] = False

        # Assume a max packet size of 64 until configured otherwise.
        self.max_packet_size_ep0 = 64

        # Start off by assuming we're not waiting for an OUT control transfer's
        # data stage.  # See handle_setup_complete_on_endpoint for details.
        self.pending_control_request = None

        # Store a reference to the device's active configuration,
        # which we'll use to know which endpoints we'll need to check
        # for data transfer readiness.
        self.configuration = None

        # Maintain a list of configured endpoints with form: (address, max_packet_size, USBTransferType)
        self.configured_endpoints = dict()
        
    def connect(self, usb_device: USBDevice, device_speed: DeviceSpeed=DeviceSpeed.FULL):
        '''
        Connect a USB device to the Cynthion hardware

        :param usb_device: USB device instance to connect
        '''
        super(CynthionPhy, self).connect(usb_device)
        
        # Quirks are not provided anywhere by UMAP2
        quirks = 0
        
        if self.device_speed != None:
            device_speed=self.device_speed
        
        if device_speed not in [DeviceSpeed.FULL, DeviceSpeed.HIGH]:
            self.warning(f"Moondancer only supports USB Full and High Speed. Ignoring requested speed: {device_speed.name}")

        self.debug(f"moondancer.connect(max_packet_size_ep0:{self.max_packet_size_ep0}, device_speed:{device_speed}, quirks:{quirks})")
        
        # Override the max packet size if provided by the USBDevice
        if usb_device.max_packet_size_ep0 is None:
            raise Exception('max_packet_size_ep0 is not set')
        
        self.api.connect(usb_device.max_packet_size_ep0, device_speed, quirks)
        
        device_name = f"{type(self.connected_device).__module__}.{type(self.connected_device).__qualname__}"
        
        self.info(f"Connected {device_speed.name} speed device '{device_name}' to target host.")

    def disconnect(self):
        '''
        Disconnect the device from the Cynthion hardware
        '''
        self.info("Disconnecting from target host.")

        self.device.comms.release_exclusive_access()
        self.api.disconnect()
        return super(CynthionPhy, self).disconnect()

    def send_on_endpoint(self, ep_num: int, data: bytes):
        '''
        Send data on a specific endpoint

        :param ep_num: number of endpoint
        :param data: data to send
        '''
        self._send_on_endpoint(ep_num, data)

    def stall_ep0(self):
        '''
        Stalls control endpoint (0)
        '''
        self._stall_endpoint(0)
        
    def ack_status_stage(self):
        '''
        Acknowledge status stage
        '''
        self._ack_status_stage()

    def run(self):
        self.service_irqs()
        
    def service_irqs(self):
        '''
        Handle USB requests
        '''
        self.stop = False
        # Constantly service any events that need to be performed.
        while not self.stop:
            
            self._service_irqs()
            
            if self.app.should_stop_phy():
                self.stop = True
                break

    # Hooks nessesary for umap2
    def pre_handle_request_hook(self, buf):
        req = USBDeviceRequest(buf)
        
        if req.request == 9:
            pass

    def post_handle_request_hook(self, buf):
        req = USBDeviceRequest(buf)
        
        if req.request == 5:# handle_set_address_request
            # Not sure if the api needs the address, but MoondancerApp does it.
            self._set_address(req.value)
        
        elif req.request == 9:#handle_set_configuration_request
            # Runs a version of the MoondancerApp.configured() method.
            
            
            # If we need to issue a configuration command, issue one.
            # (If there are no endpoints other than control, this command will be
            #  empty, and we can skip this.)
            endpoint_triplets = []

            for nr, endpoint in self.connected_device.endpoints.items():
                self.debug(f"Configuring endpoint: {endpoint}.")
                triple = (endpoint.address, endpoint.max_packet_size, endpoint.transfer_type,)
                endpoint_triplets.append(triple)

            #for interface in self.configuration.get_interfaces():
            #    for endpoint in interface.get_endpoints():#

            #        self.debug(f"Configuring endpoint: {endpoint}.")

            #        triple = (endpoint.get_address(), endpoint.max_packet_size, endpoint.transfer_type,)
            #        endpoint_triplets.append(triple)

            if len(endpoint_triplets):
                self.api.configure_endpoints(*endpoint_triplets)
                for triplet in endpoint_triplets:
                    self.configured_endpoints[triplet[0]] = triplet

            # If we've just set up endpoints, check to see if any of them
            # have NAKs waiting.
            nak_status = self.api.get_nak_status()
            self._handle_ep_in_nak_status(nak_status)

            self.info("Target host configuration complete.")
        


    # Support for USBControlRequest class from MoondancerApp to answer requests from the host
    def control_send(self, endpoint_number: int, in_request: USBControlRequest, data: bytes, *, blocking: bool = False):
        """ Queues sending data on the provided control endpoint in
            response to a IN control request.

        Args:
            endpoint_number : The endpoint number to send data upon.
            in_request      : The control request being responded to.
            data            : The data to send.
            blocking        : If provided and true, this function will block
                               until the backend indicates the send is complete.

        """
        self._send_on_control_endpoint(endpoint_number, in_request, data, blocking=blocking)

    # Additional methods from MoondancerApp

    def _set_address(self, address: int, defer: bool = False):
        """ Updates the device's knowledge of its own address.

        Args:
            address : The address to apply.
            defer   : If true, the address change should be deferred
                      until the next time a control request ends. Should
                      be set if we're changing the address before we ack
                      the relevant transaction.
        """
        self.address = address
        self.debug(f"moondancer.set_address({address}, {defer})")

        self.api.set_address(address, 1 if defer else 0)
        
    def _stall_endpoint(self, endpoint_number:int, direction: USBDirection=USBDirection.OUT):
        """
        Stalls the provided endpoint, as defined in the USB spec.

        Args:
            endpoint_number : The number of the endpoint to be stalled.
        """

        endpoint_address = (endpoint_number | 0x80) if direction else endpoint_number
        self.debug(f"Stalling EP{endpoint_number} {USBDirection(direction).name} (0x{endpoint_address:x})")

        # Mark endpoint number as stalled.
        self.endpoint_stalled[endpoint_number] = True

        # Stall endpoint address.
        if direction:
            self.api.stall_endpoint_in(endpoint_number)
            self.debug(f"  moondancer.api.stall_endpoint_in({endpoint_number})")
        else:
            self.api.stall_endpoint_out(endpoint_number)
            self.debug(f"  moondancer.api.stall_endpoint_out({endpoint_number})")
        
    def _ack_status_stage(self, direction: USBDirection=USBDirection.OUT, endpoint_number:int =0, blocking: bool=False):
        """
            Handles the status stage of a correctly completed control request,
            by priming the appropriate endpoint to handle the status phase.

            Args:
                direction : Determines if we're ACK'ing an IN or OUT vendor request.
                            (This should match the direction of the DATA stage.)
                endpoint_number : The endpoint number on which the control request
                                  occurred.
                blocking : True if we should wait for the ACK to be fully issued
                           before returning.
        """

        self.debug(f"moondancer.ack_status_stage({direction.name}, {endpoint_number}, {blocking})")

        if direction == USBDirection.OUT: # HOST_TO_DEVICE
            # If this was an OUT request, we'll prime the output buffer to
            # respond with the ZLP expected during the status stage.
            self.api.write_endpoint(endpoint_number, blocking, bytes([]))

            self.debug(f"  moondancer.api.write_endpoint({endpoint_number}, {blocking}, [])")

        else: # DEVICE_TO_HOST (IN)
            # If this was an IN request, we'll need to set up a transfer descriptor
            # so the status phase can operate correctly. This effectively reads the
            # zero length packet from the STATUS phase.
            self.api.ep_out_prime_receive(endpoint_number)

            self.debug(f"  moondancer.api.ep_out_prime_receive({endpoint_number})")
        
    def _send_on_endpoint(self, endpoint_number: int, data: bytes, blocking: bool=True):
        """
        Sends a collection of USB data on a given endpoint.

        Args:
            endpoint_number : The number of the IN endpoint on which data should be sent.
            data     : The data to be sent.
            blocking : If true, this function will wait for the transfer to complete.
        """

        self.api.write_endpoint(endpoint_number, blocking, bytes(data))

        self.debug(f"moondancer.send_on_endpoint({endpoint_number}, {len(data)}, {blocking})")
        self.debug(f"  moondancer.api.write_endpoint({endpoint_number}, {blocking}, {len(data)})")
        

    def _read_from_endpoint(self, endpoint_number: int) -> bytes:
        """
        Reads a block of data from the given endpoint.

        Args:
            endpoint_number : The number of the OUT endpoint on which data is to be rx'd.
        """

        self.debug(f"moondancer.read_from_endpoint({endpoint_number})")

        # Read from the given endpoint...
        data = self.api.read_endpoint(endpoint_number)

        # Re-enable OUT interface to receive data again...
        self.api.ep_out_interface_enable()

        self.debug(f"  moondancer.api.read_endpoint({endpoint_number}) -> {len(data)} '{data}'")

        # Finally, return the result.
        return data
      
    def _send_on_control_endpoint(self, endpoint_number: int, in_request: USBControlRequest, data: bytes, blocking: bool=True):
        """
        Sends a collection of USB data in response to a IN control request by the host.

        Args:
            endpoint_number  : The number of the IN endpoint on which data should be sent.
            requested_length : The number of bytes requested by the host.
            data             : The data to be sent.
            blocking         : If true, this function should wait for the transfer to complete.
        """
        requested_length = in_request.length
        self.api.write_control_endpoint(endpoint_number, requested_length, blocking, bytes(data))

        self.debug(f"moondancer.send_on_control_endpoint({endpoint_number}, {requested_length}, {len(data)}, {blocking})")
        self.debug(f"  moondancer.api.write_control_endpoint({endpoint_number}, {requested_length}, {blocking}, {len(data)})")
     
    def _clear_halt(self, endpoint_number: int, direction: USBDirection):
        """ Clears a halt condition on the provided non-control endpoint.

        Args:
            endpoint_number : The endpoint number
            direction       : The endpoint direction; or OUT if not provided.
        """

        endpoint_address = (endpoint_number | 0x80) if direction else endpoint_number
        self.debug(f"Clearing halt EP{endpoint_number} {USBDirection(direction).name} (0x{endpoint_address:x})")

        self.api.clear_feature_endpoint_halt(endpoint_number, direction)
        self.debug(f"  moondancer.api.clear_feature_endpoint_halt({endpoint_number}, {direction})")
        
    def _service_irqs(self):
        """
        Core routine of the Facedancer execution/event loop. Continuously monitors the
        Moondancer's execution status, and reacts as events occur.
        """

        # Get latest interrupt events
        events: List[Tuple[int, int]] = self.api.get_interrupt_events()

        # Handle interrupt events.
        if len(events) > 0:

            # gcp doesn't seem to return a nested tuple if it's only one event
            if isinstance(events[0], int):
                events = [ events ]

            parsed_events = [InterruptEvent(event) for event in events]

            for event in parsed_events:
                self.debug(f"MD IRQ => {event}")
                if event == InterruptEvent.USB_BUS_RESET:
                    self._handle_bus_reset()
                elif event == InterruptEvent.USB_RECEIVE_CONTROL:
                    self._handle_receive_control(event.endpoint_number)
                elif event == InterruptEvent.USB_RECEIVE_PACKET and event.endpoint_number == 0:
                    # TODO support endpoints other than EP0
                    self._handle_receive_control_packet(event.endpoint_number)
                elif event == InterruptEvent.USB_RECEIVE_PACKET:
                    self._handle_receive_packet(event.endpoint_number)
                elif event == InterruptEvent.USB_SEND_COMPLETE:
                    self._handle_send_complete(event.endpoint_number)
                else:
                    self.error(f"Unhandled interrupt event: {event}")

        # Check EP_IN NAK status for pending data requests
        else:
            nak_status = self.api.get_nak_status()
            if nak_status != 0:
                self._handle_ep_in_nak_status(nak_status)

    # - Interrupt event handlers ----------------------------------------------

    # USB0_BUS_RESET
    def _handle_bus_reset(self):
        """
        Triggers Moondancer to perform its side of a bus reset.
        """

        #if self.connected_device:
        #    self.connected_device.handle_bus_reset()
        #else:
        #    self.api.bus_reset()
        
        # USBDevice from umap2 has no handle_bus_reset method, so we just call the api directly
        self.info("Host issued a bus reset; resetting our connection.")

        # Clear our state back to address zero and no configuration.
        self.configuration = None
        #self.address = 0
        
        self.debug(f"moondancer.bus_reset()")
        self.api.bus_reset()

    # USB0_RECEIVE_CONTROL
    def _handle_receive_control(self, endpoint_number: int):
        """
        Handles a known outstanding control event on a given endpoint.

        endpoint_number: The endpoint number for which a control event should be serviced.
        """

        self.debug(f"handle_receive_control({endpoint_number})")

        # HACK: to maintain API compatibility with the existing facedancer API,
        # we need to know if a stall happens at any point during our handler.
        self.endpoint_stalled[endpoint_number] = False

        # Read the data from the SETUP stage...
        data    = bytearray(self.api.read_control())
        # !umap2 has no constructor for a request. It just uses the plain bytearray.
        #request = self.connected_device.create_request(data)
        request = USBControlRequest.from_raw_bytes(data, device=self)

        self.debug(f"  moondancer.api.read_control({endpoint_number}) -> {len(data)} '{request}'")

        is_out   = request.get_direction() == USBDirection.OUT # HOST_TO_DEVICE
        has_data = (request.length > 0)
        self.debug(f"  is_out:{is_out}  has_data:{has_data}")

        # Special case: if this is an OUT request with a data stage, we won't
        # handle the request until the data stage has been completed. Instead,
        # we'll stash away the data received in the setup stage, prime the
        # endpoint for the data stage, and then wait for the data stage to
        # complete, triggering a corresponding code path in
        # in handle_transfer_complete_on_endpoint.
        if is_out and has_data:
            self.debug(f"  setup packet has data - queueing read")
            self.pending_control_request = request
            self.api.ep_out_prime_receive(endpoint_number)
            return

        # Pass the request to the emulated device for handling.
        self.debug(f"  connected_device.handle_request({request})")
        
        # !umap2 required the raw bytes to create its own request object.
        self.pre_handle_request_hook(data)
        self.connected_device.handle_request(data)
        self.post_handle_request_hook(data)

        # If it was an IN request with a data stage we now need to
        # prime the endpoint to receive a ZLP from the host
        # acknowledging receipt of our response.
        if has_data and not is_out and not self.endpoint_stalled[endpoint_number]:
            self.debug(f"  CONTROL IN -> prime ep to receive zlp")
            self.api.ep_out_prime_receive(endpoint_number)


     # USB0_RECEIVE_PACKET(0)
    def _handle_receive_control_packet(self, endpoint_number: int):
        self.debug(f"moondancer.handle_receive_control_packet({endpoint_number}) pending:{self.pending_control_request}")

        # Handle packet if we don't have a pending control request
        if not self.pending_control_request:
            data = self.api.read_endpoint(endpoint_number)
            if len(data) == 0:
                # It's a zlp following an IN control transfer, re-enable interface for reception on other endpoints.
                self.api.ep_out_interface_enable()
            else:
                self.error(f"Discarding {len(data)} bytes on control endpoint with no pending control request")
            return

        # We have a pending control request with a data stage...
        # Read the rest of the data from the endpoint, completing the control request.
        new_data = self.api.read_endpoint(endpoint_number)

        self.debug(f"  handling control data stage: {len(new_data)} bytes")
        self.debug(f"  moondancer.api.read_endpoint({endpoint_number}) -> {len(new_data)}")

        if len(new_data) == 0:
            # It's a zlp following a control IN transfer, re-enable interface for reception on other endpoints.
            self.api.ep_out_interface_enable()
            self.debug(f"ZLP ending Control IN transfer on ep: {endpoint_number}")
            return

        # Append our new data to the pending control request.
        self.pending_control_request.data.extend(new_data)

        all_data_received = len(self.pending_control_request.data) == self.pending_control_request.length
        is_short_packet   = len(new_data) < self.max_packet_size_ep0

        if all_data_received or is_short_packet:
            # Handle the completed setup request...
            # !Transform self.pending_control_request (USBControlRequest) to raw bytes for umap2's USBDevice own USBDeviceRequest constructor
            # self.connected_device.handle_request(self.pending_control_request)
            self.pre_handle_request_hook(self.pending_control_request.raw() + self.pending_control_request.data)
            self.connected_device.handle_request(self.pending_control_request.raw() + self.pending_control_request.data)
            self.post_handle_request_hook(self.pending_control_request.raw() + self.pending_control_request.data)

            # And clear our pending setup data.
            self.pending_control_request = None

            # Finally, re-enable interface for reception on other endpoints.
            self.api.ep_out_interface_enable()

            return

        # Finally, re-prime our control endpoint to receive the rest of the control data.
        self.api.ep_out_prime_receive(endpoint_number)       
            
    # USB0_RECEIVE_PACKET(1...15)
    def _handle_receive_packet(self, endpoint_number: int):
        """
        Handles a known-completed transfer on a given endpoint.

        Args:
            endpoint_number : The endpoint number for which the transfer should be serviced.
        """

        self.debug(f"moondancer.handle_receive_packet({endpoint_number})")

        # Read the data from the endpoint
        data = self.api.read_endpoint(endpoint_number)

        self.debug(f"  moondancer.api.read_endpoint({endpoint_number}) -> {len(data)}")

        # Ignore it if it's a ZLP ack as Facedancer devices don't handle it.
        if len(data) == 0:
            # Finally, Prime endpoint to receive again.
            self.api.ep_out_interface_enable()
            self.debug(f"  ZLP ending Bulk IN transfer on ep: {endpoint_number}")
            return

        # Pass it to the device's handler
        self.connected_device.handle_data_available(endpoint_number, data)

        # Finally, re-enable other OUT endpoints so we can receive on them again.
        self.api.ep_out_interface_enable()        

    # USB0_SEND_COMPLETE
    def _handle_send_complete(self, endpoint_number: int):
        self.debug(f"handle_send_complete({endpoint_number})")
        pass

    # Handle pending data requests on EP_IN
    def _handle_ep_in_nak_status(self, nak_status: int):
        nakked_endpoints = [epno for epno in range(self.SUPPORTED_ENDPOINTS) if (nak_status >> epno) & 1]
        for endpoint_number in nakked_endpoints:
            if endpoint_number != 0:
                self.debug(f"Received IN NAK on ep{endpoint_number}")
                # !!!not supported by umap2
                #self.connected_device.handle_nak(endpoint_number)        
            
            
            
            
            
            
            
            
            
            
            
            
    # Static methods

    @classmethod
    def appropriate_for_environment(cls, backend_name: str) -> bool:
        """
        Determines if the current environment seems appropriate
        for using the Moondancer backend.
        """

        # Check: if we have a backend name other than moondancer,
        # the user is trying to use something else. Abort!
        if backend_name and backend_name != "cynthion":
            return False

        # If we're not explicitly trying to use something else,
        # see if there's a connected Cynthion.
        try:
            import cynthion
            device = cynthion.Cynthion()
            return device.supports_api('moondancer')
        except ImportError:
            cls.info("Skipping Cynthion-based devices, as the cynthion python module isn't installed.")
            return False
        except IOError:
            cls.warning("Found Cynthion-based device, but could not access it. (Check permissions?)")
            return False
        except:
            return False
    
    