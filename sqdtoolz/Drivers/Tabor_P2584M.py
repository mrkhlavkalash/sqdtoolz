import os
import sys
from sqdtoolz.Drivers.Dependencies.teproteus import TEProteusAdmin as TepAdmin
from sqdtoolz.Drivers.Dependencies.teproteus import TEProteusInst as TepInst

import numpy as np
import math
import time

from qcodes import Instrument, InstrumentChannel, validators as vals
from qcodes.instrument.parameter import ManualParameter

import numpy as np
from functools import partial

from copy import deepcopy

class AWG_TaborP2584M_channel(InstrumentChannel):
    """
    AWG Channel class for the Tabor Proteus RF Transceiver
    """
    def __init__(self, parent:Instrument, name:str, channel: int) -> None:
        """
        Class Constructor
        """
        super().__init__(parent, name)
        self._parent = parent
        self._channel = channel
        self._outputEnable = True
        self._amp = 1.0
        self._off = 0.0

        self.add_parameter(
            'amplitude', label='Amplitude', unit='Vpp',
            get_cmd=partial(self._get_cmd, ':SOUR:VOLT:AMPL?'),
            set_cmd=partial(self._set_cmd, ':SOUR:VOLT:AMPL'),
            vals=vals.Numbers(1e-3, 1.2),
            get_parser=lambda x : float(x),
            set_parser=lambda x: x)
        self.add_parameter(
            'offset', label='Offset', unit='V',
            get_cmd=partial(self._get_cmd, ':SOUR:VOLT:OFFS?'),
            set_cmd=partial(self._set_cmd, ':SOUR:VOLT:OFFS'),
            vals=vals.Numbers(-0.5, 0.5),
            inter_delay=0.0001,
            step=0.5,
            get_parser=float)
        self.add_parameter(
            'output', label='Output Enable',
            get_cmd=partial(self._get_cmd, ':OUTP?'),
            set_cmd=partial(self._set_cmd, ':OUTP'),
            val_mapping={True: 'ON', False: 'OFF'})

        self.add_parameter(
            'trig_src', label='Output Enable',
            parameter_class=ManualParameter,
            initial_value='NONE',
            vals=vals.Enum('NONE','TRG1','TRG2'))
        
        self.amplitude(1.2)

        #Marker parameters
        for cur_mkr in [1,2]:
            self.add_parameter(
                f'marker{cur_mkr}_output', label=f'Channel {channel} Marker {cur_mkr-1} output',
                get_cmd=partial(self._get_mkr_cmd, ':MARK?', cur_mkr),
                set_cmd=partial(self._set_mkr_cmd, ':MARK', cur_mkr),
                val_mapping={True: 'ON', False: 'OFF'})
            getattr(self, f'marker{cur_mkr}_output')(True)  #Default state is ON
            self._set_mkr_cmd(':MARK:VOLT:PTOP', cur_mkr, 1.2)
            #TODO: Maybe parametrise this? But it will be set to maximum range for now...  
            self._set_mkr_cmd(':MARKer:VOLTage:OFFSet', cur_mkr, 0.0)
            self._set_mkr_cmd(':MARK:VOLT:PTOP', cur_mkr, 1.2)

        #NOTE: Although the ramp-rate is technically software-based, there could be a source that provides actual precision rates - so it's left as a parameter in general instead of being a HAL-level feature...
        self.add_parameter('voltage_ramp_rate', unit='V/s',
                        label="Output voltage ramp-rate",
                        initial_value=2.5e-3/0.05,
                        vals=vals.Numbers(0.001, 1),
                        get_cmd=lambda : self.offset.step/self.offset.inter_delay,
                        set_cmd=self._set_ramp_rate)
        self.voltage_ramp_rate(1)



    def _get_cmd(self, cmd):
        #Perform channel-select
        self._parent.parent._inst.send_scpi_cmd(f':INST:CHAN {self._channel}')
        #Query command
        return self._parent.parent._inst.send_scpi_query(cmd)

    def _set_cmd(self, cmd, value):
        #Perform channel-select
        self._parent.parent._inst.send_scpi_cmd(f':INST:CHAN {self._channel}')
        #Perform command
        self._parent.parent._inst.send_scpi_cmd(f'{cmd} {value}')

    def _get_mkr_cmd(self, cmd, mkr_num):
        #Perform channel-select
        self._parent.parent._inst.send_scpi_cmd(f':INST:CHAN {self._channel}')
        #Perform marker-select
        self._parent.parent._inst.send_scpi_cmd(f':MARK:SEL {mkr_num}')
        #Perform command
        return self._parent.parent._inst.send_scpi_query(cmd)

    def _set_mkr_cmd(self, cmd, mkr_num, value):
        #Perform channel-select
        self._parent.parent._inst.send_scpi_cmd(f':INST:CHAN {self._channel}')
        #Perform marker-select
        self._parent.parent._inst.send_scpi_cmd(f':MARK:SEL {mkr_num}')
        #Perform command
        self._parent.parent._inst.send_scpi_cmd(f'{cmd} {value}')


    @property
    def Parent(self):
        return self._parent
        
    @property
    def Amplitude(self):
        return self.amplitude()
    @Amplitude.setter
    def Amplitude(self, val):
        self.amplitude(val)
        
    @property
    def Offset(self):
        return self.offset()
    @Offset.setter
    def Offset(self, val):
        self.offset(val)
        
    @property
    def Output(self):
        return self.output()
    @Output.setter
    def Output(self, boolVal):
        self.output(boolVal)

    @property
    def Voltage(self):
        return self.offset()
    @Voltage.setter
    def Voltage(self, val):
        self.offset(val)
        
    @property
    def RampRate(self):
        return self.voltage_ramp_rate()
    @RampRate.setter
    def RampRate(self, val):
        self.voltage_ramp_rate(val)

    def _set_ramp_rate(self, ramp_rate):
        if ramp_rate < 0.01:
            self.offset.step = 0.001
        elif ramp_rate < 0.1:
            self.offset.step = 0.010
        elif ramp_rate < 1.0:
            self.offset.step = 0.100
        else:
            self.offset.step = 1.0
        self.offset.inter_delay = self.offset.step / ramp_rate

class AWG_TaborP2584M_task:
    def __init__(self, seg_num, num_cycles, next_task_ind, trig_src='NONE'):
        self.seg_num = seg_num
        self.num_cycles = num_cycles
        self.next_task_ind = next_task_ind  #NOTE: Indexed from 1
        self.trig_src = trig_src

class TaborP2584M_AWG(InstrumentChannel):
    """
    Instrument class for the Tabor Proteus RF transceiver AWG side
    Inherits from InstrumentChannel 
    """
    def __init__(self, parent):
        super().__init__(parent, 'AWG')
        self._parent = parent

        self.add_parameter(
            'activeChannel', label='Currently Selected Channel', 
            get_cmd=partial(self._parent._get_cmd, ':INST:CHAN?'),
            set_cmd=partial(self._parent._set_cmd, ':INST:CHAN'), 
            vals = vals.Enum(1, 2, 3, 4))

        self.add_parameter(
            'sample_rate', label='Sample Rate', unit='Hz',
            get_cmd=partial(self._parent._get_cmd, ':SOUR:FREQ:RAST?'),
            set_cmd=partial(self._parent._set_cmd, ':SOUR:FREQ:RAST'),
            vals=vals.Numbers(1e9, 9e9),    #Note that this is a cheat using Nyquist trickery...
            get_parser=float)

        # Reset memory in all output channels !CHECK!
        for m in range(4):
            self.activeChannel(m + 1)
            #self._parent._set_cmd(':INST:CHAN', m+1)
            self._parent._send_cmd(':TRAC:DEL:ALL')      
            self._parent._send_cmd(':TASK:ZERO:ALL')       #Does this need to be run per channel?!

        #Get the DAC mode (8 bits or 16 bits)
        dac_mode = self._parent._get_cmd(':SYST:INF:DAC?')
        if dac_mode == 'M0' :
            self._max_dac = 65535
            self._data_type = np.uint16 
        else:
            self._max_dac = 255
            self._data_type = np.uint8 
        self._half_dac = self._max_dac // 2.0

        #Get number of channels
        self._num_channels = int(self._parent._get_cmd(":INST:CHAN? MAX"))
        #Get the maximal number of segments
        self._max_seg_number = int(self._parent._get_cmd(":TRACe:SELect:SEGMent? MAX"))
        #Get the available memory in bytes of wavform-data (per DDR):
        self._arbmem_capacity_bytes = int(self._parent._get_cmd(":TRACe:FREE?"))
        
        #Setup triggering
        # self._set_cmd(':TRIG:SOUR:ENAB', 'TRG1')
        self._parent._set_cmd(':TRIG:SEL', 'TRG1')
        self._parent._set_cmd(':TRIG:STAT', 'ON')
        self._parent._set_cmd(':TRIG:LEV', 0.3)
        self._parent._set_cmd(':TRIG:SEL', 'TRG2')
        self._parent._set_cmd(':TRIG:STAT', 'OFF')
        self._parent._set_cmd(':TRIG:SEL', 'INT')
        self._parent._set_cmd(':TRIG:STAT', 'OFF')
        # self._set_cmd(':INIT:CONT', 'OFF')

        self._trigger_edge = 1

        self._ch_list = ['CH1', 'CH2', 'CH3', 'CH4']

        # Output channels added to both the module for snapshots and internal Trigger Sources for the DDG HAL...
        for ch_ind, ch_name in enumerate(self._ch_list):
            cur_channel = AWG_TaborP2584M_channel(self, ch_name, ch_ind+1)
            self.add_submodule(ch_name, cur_channel)
            cur_channel.marker1_output(True)
            cur_channel.marker2_output(True)
        self._used_memory_segments = [None]*2

        self._sequence_lens = [None]*4

    @property
    def SampleRate(self):
        return self.sample_rate()
    @SampleRate.setter
    def SampleRate(self, frequency_hertz):
        self.sample_rate(frequency_hertz)

    @property
    def TriggerInputEdge(self):
        return self._trigger_edge
    @TriggerInputEdge.setter
    def TriggerInputEdge(self, pol):
        self._trigger_edge = pol

    def num_supported_markers(self, channel_name):
        return 2

    @property
    def AutoCompressionSupport(self):
        return {'Supported' : True, 'MinSize' : 1024, 'Multiple' : 32}

    @property
    def MemoryRequirements(self):
        return {'MinSize' : 1024, 'Multiple' : 32}

    def _get_channel_output(self, identifier):
        if identifier in self.submodules:
            return self.submodules[identifier]  #!!!NOTE: Note from above in the initialiser regarding the parent storing the AWG channel submodule
        else:
            return None

    def prepare_waveform_memory(self, chan_id, seg_lens, **kwargs):
        """
        Method to prepare waveform for Tabor memory
        @param chan_id: Id of the channel to prepare memory for
        @param seg_lens: length of segments to program
        """
        chan_ind = self._ch_list.index(chan_id)
        self._sequence_lens[chan_ind] = seg_lens
        self._banks_setup = False

    def _setup_memory_banks(self):
        """
        Method to prepare memory banks for programming
        For the Tabor, CH1 and CH2 share a memory bank
        and CH3 and CH3 share a memory bank
        """
        if self._banks_setup:
            return

        # Compute offsets of data if two channels sharing a memory banke are being used
        # I.e. store it as CH1-Data, then CH2-Data. Similarly in the other memory bank, it's CH3-Data, then CH4-Data
        if self._sequence_lens[0] != None:
            self._seg_off_ch2 = len(self._sequence_lens[0])
        else:
            self._seg_off_ch2 = 0
        if self._sequence_lens[2] != None:
            self._seg_off_ch4 = len(self._sequence_lens[2])
        else:
            self._seg_off_ch4 = 0

        #Settle Memory Bank 1 (shared among channels 1 and 2) and Memory Bank 2 (shared among channels 3 and 4)
        seg_id = 1
        reset_remaining = False
        for cur_ch_ind in range(4):
            if cur_ch_ind == 2:
                seg_id = 1      #Going to the next memory bank now...
                reset_remaining = False
            if self._sequence_lens[cur_ch_ind] != None:
                #Select current channel
                self._parent._set_cmd(':INST:CHAN', cur_ch_ind+1) #NOTE I'm assuming cur_ch_index is zero indexed adn the command is 1 indexed, hence the +1
                for cur_len in self._sequence_lens[cur_ch_ind]:
                    self._parent._set_cmd(':TRACe:SEL', seg_id) # Select segment for clearing
                    cur_mem_len = self._parent._get_cmd(':TRAC:DEF:LENG?') # Find length of segment
                    if reset_remaining or cur_mem_len == '' or cur_len != int(cur_mem_len):
                        self._parent._set_cmd(':TRAC:DEL', seg_id) # Clear the current segment
                        reset_remaining = True #NOTE UNSURE OF THIS LOGIC
                    self._parent._send_cmd(f':TRAC:DEF {seg_id}, {cur_len}') # Specify a segment and its corresponding length
                    seg_id += 1
            self._sequence_lens[cur_ch_ind] = None

        self._banks_setup = True

    def program_channel(self, chan_id, dict_wfm_data):
        """
        Method to program channel
        @param chan_id: Id of channel to be programmed
        @param dict_wfm_data: wfm data to be programmed
        """
        chan_ind = self._ch_list.index(chan_id)
        cur_chnl = self._get_channel_output(chan_id)

        self._setup_memory_banks()

        # Setup segment offsets
        if chan_ind == 1:
            seg_offset = self._seg_off_ch2
        elif chan_ind == 3:
            seg_offset = self._seg_off_ch4
        else:
            seg_offset = 0

        #Select channel
        self._parent._set_cmd(':INST:CHAN', chan_ind+1)

        #Program the memory banks
        for m in range(len(dict_wfm_data['waveforms'])):
            cur_data = dict_wfm_data['waveforms'][m]
            cur_amp = cur_chnl.Amplitude/2
            cur_off = cur_chnl.Offset   #Don't compensate for offset... # NOTE: this used to be multiplied by 0
            cur_data = (cur_data - cur_off)/cur_amp
            assert (max(cur_data) < np.abs(cur_chnl.Amplitude + cur_chnl.Offset)), "The Amplitude and Offset are too large, output will be saturated"
            self._send_data_to_memory(m+1 + seg_offset, cur_data, dict_wfm_data['markers'][m])
        #Program the task table...
        task_list = []
        for m, seg_id in enumerate(dict_wfm_data['seq_ids']):
            task_list += [AWG_TaborP2584M_task(seg_id+1 + seg_offset, 1, (m+1)+1)]
        task_list[0].trig_src = cur_chnl.trig_src()     #First task is triggered off the TRIG source
        task_list[-1].next_task_ind = 1                 #Last task maps back onto the first task
        self._program_task_table(chan_ind+1, task_list)
        
        self._parent._set_cmd('FUNC:MODE', 'TASK')
        # Ensure all previous commands have been executed
        while not self._parent._get_cmd('*OPC?'):
            pass

    def _program_task_table(self, channel_index, tasks):
        #Select current channel
        self._parent._set_cmd(':INST:CHAN', channel_index)
        #Allocate a set number of rows for the task table
        assert len(tasks) < 64*10e3, "The maximum amount of tasks that can be programmed is 64K"
        self._parent._set_cmd(':TASK:COMP:LENG', len(tasks))

        #Check that there is at most one trigger source and record it if applicable
        cur_trig_src = ''
        for cur_task in tasks:
            if cur_task.trig_src != '' and cur_task.trig_src != 'NONE':
                assert cur_trig_src == '' or cur_trig_src == cur_task.trig_src, "Cannot have multiple trigger sources for a given Tabor channel input."
                cur_trig_src = cur_task.trig_src

        for task_ind, cur_task in enumerate(tasks):
            self._parent._set_cmd(':TASK:COMP:SEL', task_ind + 1)
            #Set the task to be solitary (i.e. not a part of an internal sequence inside Tabor...)
            self._parent._send_cmd(':TASK:COMP:TYPE SING')
            #Set task parameters...
            self._parent._set_cmd(':TASK:COMP:LOOP', cur_task.num_cycles)
            self._parent._set_cmd(':TASK:COMP:SEGM', cur_task.seg_num)
            self._parent._set_cmd(':TASK:COMP:NEXT1', cur_task.next_task_ind)
            self._parent._set_cmd(':TASK:COMP:ENAB', cur_task.trig_src)
      
        #Download task table to channel
        self._parent._send_cmd(':TASK:COMP:WRIT')
        # self._set_cmd(':FUNC:MODE', 'TASK')

        #Check for errors...
        self._parent._chk_err('after writing task table.')

        #Enable triggers if applicable to this channel
        if cur_trig_src != '':
            #Select current channel (just in case)
            self._parent._set_cmd(':INST:CHAN', channel_index)
            #Enable triggers...
            self._parent._set_cmd(':TRIG:SEL', cur_trig_src)
            self._parent._set_cmd(':TRIG:STAT', 'ON')
        
    def _send_data_to_memory(self, seg_ind, wfm_data_normalised, mkr_data):
        #Condition the data
        final_data = (wfm_data_normalised * self._half_dac + self._half_dac).astype(self._data_type)
        #Select the segment
        self._parent._set_cmd(':TRAC:SEL', seg_ind)
        #Increase the timeout before writing binary-data:
        self._parent._inst.timeout = 1000000
        #Send the binary-data with *OPC? added to the beginning of its prefix.
        #self._parent._inst.write_binary_data('*OPC?; :TRAC:DATA', final_data*0)
        #!!!There seems to be some API changes that basically breaks their code - removing OPC for now...
        if self._parent._debug:
            self._parent._debug_logs += 'BINARY-DATA-TRANSFER: :TRAC:DATA'
        self._parent._inst.write_binary_data(':TRAC:DATA', final_data)
        #Read the response to the *OPC? query that was added to the prefix of the binary data
        #resp = self._inst.()
        #Set normal timeout
        self._parent._inst.timeout = 10000
        #Check for errors...
        self._parent._chk_err('after writing binary values to AWG waveform memory.')

        total_mkrs = np.array([])
        for mkr_ind, cur_mkr_data in enumerate(mkr_data):
            if mkr_data[mkr_ind].size == 0:
                continue
            # self._set_cmd(':MARK:SEL', mkr_ind+1)

            if self._data_type == np.uint16:
                cur_mkrs = mkr_data[mkr_ind][::2].astype(np.uint8)
            else:
                #cur_mkrs = mkr_data[mkr_ind][::4].astype(np.uint8)
                assert False, "Unsupported format! Why is it not even 16-bit anyway? Read the manual to support this format..."
            #Bit 0 for MKR1, Bit 1 for MKR2 - must perform bit-shifts if it's MKR3 or MKR4, but these outputs are not present in this module...
            if mkr_ind == 0:
                cur_mkrs *= 1
            elif mkr_ind == 1:
                cur_mkrs *= 2
            #
            if total_mkrs.size == 0:
                total_mkrs = cur_mkrs
            else:
                total_mkrs += cur_mkrs
        #
        if total_mkrs.size > 0:            
            #The arrangement four MSBs are for the even marker segments while the four LSBs are for the odd marker segments (starting the count at 1)
            total_mkrs = total_mkrs[0::2] + np.left_shift(total_mkrs[1::2], 4)
            #Increase the timeout before writing binary-data:
            self._parent._inst.timeout = 30000
            # Send the binary-data with *OPC? added to the beginning of its prefix.
            if self._parent._debug:
                self._parent._debug_logs += 'BINARY-DATA-TRANSFER: :MARK:DATA'
            self._parent._inst.write_binary_data(':MARK:DATA', total_mkrs)
            # Read the response to the *OPC? query that was added to the prefix of the binary data
            #resp = inst.read()
            # Set normal timeout
            self._parent._inst.timeout = 10000
            self._parent._chk_err('after writing binary values to AWG marker memory.')

class TaborP2584M_ACQ(InstrumentChannel):
    """
    Tabor Acquisition class for Proteus RF Transceiver
    Device has 2 input channels CH1 and CH2 and either 
    digitizes in dual mode or single mode. For now, 
    this driver only operates in dual mode (separate signals on each acquistion channel)
    """
    def __init__(self, parent):
        super().__init__(parent, 'ACQ')
        self._parent = parent
        self._ch_states = [False, False] # Stores which channels are enabled.
        self._active_channel = "CH1"

        self.add_parameter(
            'activeChannel', label='Currently Selected Channel', 
            get_cmd=partial(self._parent._get_cmd, ':DIG:CHAN?'),
            set_cmd=partial(self._parent._set_cmd, ':DIG:CHAN'), 
            vals = vals.Enum(1, 2))

        # Add all channel dependent parameters
        for i in range(2) :
            self.add_parameter(
                f'channel{i + 1}State', label='Currently Selected Channel', 
                get_cmd=partial(self._chan_get_cmd, i + 1, ':DIG:CHAN:STAT?'),
                set_cmd=partial(self._chan_set_cmd, i + 1,':DIG:CHAN:STAT'),
                val_mapping = {0 : "DIS", 1 : "ENAB"})
            
            self.add_parameter(
                f'channel{i + 1}Range', label='Input Range of Acquisition Channels', unit = "mVpp",
                get_cmd=partial(self._chan_get_cmd, i + 1, ':DIG:CHAN:RANG?'),
                set_cmd=partial(self._chan_set_cmd, i + 1, ':DIG:CHAN:RANG'),
                val_mapping={250 : "LOW", 400 : "MED", 500 : "HIGH"})

            # TODO : FIGURE OUT HOW TO ADD IN TASK SELECTION HERE
            self.add_parameter(
                f'trigger{i + 1}Source', label='Source of trigger for selected channel',
                get_cmd=partial(self._chan_get_cmd, i + 1, ':DIG:TRIG:SOUR?'),
                set_cmd=partial(self._chan_set_cmd, i + 1, ':DIG:TRIG:SOUR'),
                val_mapping = {"CPU" : "CPU", "EXT" : "EXT", "CH1" : "CH1", "CH2" : "CH2"},
                initial_value = "EXT")

            self.add_parameter(
                f'channel{i + 1}Offset', label='Input Offset of Acquisition Channels', unit = "V",
                get_cmd=partial(self._chan_get_cmd, i + 1, ':DIG:CHAN:OFFS?'),
                set_cmd=partial(self._chan_set_cmd, i + 1, ':DIG:CHAN:OFFS'),
                vals=vals.Numbers(-2.0, 2.0))

            self.add_parameter(
                f'trigger{i + 1}Level', label='Input level required to trigger', unit = "V",
                get_cmd=partial(self._parent._get_cmd, f':DIG:TRIG:LEV{i+1}?'),
                set_cmd=partial(self._parent._set_cmd, f':DIG:TRIG:LEV{i+1}'),
                vals=vals.Numbers(-5.0, 5.0))

            

        self.add_parameter(
            'sample_rate', label='Sample Rate', unit='Hz',
            get_cmd=partial(self._parent._get_cmd, ':DIG:FREQ?'),
            set_cmd=partial(self._parent._set_cmd, ':DIG:FREQ'),
            vals=vals.Numbers(800e6, 2.7e9),
            get_parser=float)

        self.add_parameter('trigPolarity', label='Trigger Input Polarity', 
            docstring='Polarity of the trigger input. Use with care.',
            get_cmd=partial(self._parent._get_cmd, ':DIG:TRIG:SLOP?'),
            set_cmd=partial(self._parent._set_cmd, ':DIG:TRIG:SLOP'),
            val_mapping={1: 'POS', 0: 'NEG'})

        self.add_parameter(
            'blocksize', label='Blocksize',
            parameter_class=ManualParameter,
            initial_value=2**6,
            vals=vals.Numbers())

        self.add_parameter(
            'acq_mode', label='Mode of the Digitizer',
            get_cmd=partial(self._parent._get_cmd, ':DIG:MODE?'),
            set_cmd=partial(self._parent._set_cmd, ':DIG:MODE'),
            val_mapping = {"DUAL" : "DUAL", "SING" : "SING"})

        self.add_parameter(
            'ddc_mode', label='DDC Mode of the Digitizer',
            get_cmd=partial(self._parent._get_cmd, ':DIG:DDC:MODE?'),
            set_cmd=partial(self._parent._set_cmd, ':DIG:DDC:MODE'),
            val_mapping = {"REAL" : "REAL", "COMP" : "COMP", "COMPlex" : "COMP", "N/A" : "N/A"},
            initial_value = "REAL")

        self.add_parameter(
            'ddr1_store', label='Data path to be stored in DDR1',
            get_cmd=partial(self._parent._get_cmd, ':DSP:STOR1?'),
            set_cmd=partial(self._parent._set_cmd, ':DSP:STOR1'),
            val_mapping = {"DIR1" : "DIR1", "DIR2" : "DIR2", "DSP1":"DSP1",\
                "DSP2":"DSP2", "DSP3":"DSP3", "DSP4":"DSP4", "FFTI":"FFTI",\
                "FFTO":"FFTO"},
            initial_value = "DIR1")

        self.add_parameter(
            'ddr2_store', label='Data path to be stored in DDR2',
            get_cmd=partial(self._parent._get_cmd, ':DSP:STOR2?'),
            set_cmd=partial(self._parent._set_cmd, ':DSP:STOR2'),
            val_mapping = {"DIR1" : "DIR1", "DIR2" : "DIR2", "DSP1":"DSP1",\
                "DSP2":"DSP2", "DSP3":"DSP3", "DSP4":"DSP4", "FFTI":"FFTI",\
                "FFTO":"FFTO"},
            initial_value = "DIR2")

        self.add_parameter(
            'iq_demod', label='Select IQ demodulation block to configure (REAL mode)',
            get_cmd=partial(self._parent._get_cmd, ':DSP:IQD:SEL?'),
            set_cmd=partial(self._parent._set_cmd, ':DSP:IQD:SEL'),
            val_mapping = {"DBUG":"DBUG", "IQ4":"IQ4", "IQ5":"IQ5", "IQ6":"IQ6",\
                "IQ7":"IQ7"})

        """
        self.add_parameter(
            'iq_path', label='Select IQ input path to configure',
            get_cmd=partial(self._parent._get_cmd, ':DSP:IQP:SEL?'),
            set_cmd=partial(self._parent._set_cmd, ':DSP:IQP:SEL'),
            val_mapping = {"DSP1":"DSP1", "DSP2":"DSP2", "DSP3":"DSP3", "DSP4":"DSP4"},
            initial_value = "DSP1")
        """

        self.add_parameter(
            'fir_block', label='Select FIR block to configure',
            get_cmd=partial(self._parent._get_cmd, ':DSP:FIR:SEL?'),
            set_cmd=partial(self._parent._set_cmd, ':DSP:FIR:SEL'),
            val_mapping = {"I1":"I1", "Q1":"Q1", "I2":"I2", "Q2":"Q2", \
                "DBUGI":"DBUGI", "DBUGQ":"DBUGQ"})

        self.add_parameter(
            'extTriggerType', label='type of trigger that will be derived from the external trigger of the digitizer',
            get_cmd=partial(self._parent._get_cmd, ':DIG:TRIG:TYPE?'),
            set_cmd=partial(self._parent._set_cmd, ':DIG:TRIG:TYPE'),
            val_mapping = {"EDGE" : "EDGE", "GATE" : "GATE", "WEDGE" : "WEDGE", "WGATE" : "WGATE"})

        # Setup the digitizer in two-channels mode
        self.acq_mode('DUAL')
        self.sample_rate(2.0e9)

        # Set Trigger level to 0.5V
        self.trigger1Level(0.1)
        self.trigger2Level(0.1)
        
        # Set Channel range to max
        self.channel1Range(500)
        self.channel2Range(500)

        # Set Channel offset to minimum
        self.channel1Offset(0.0)
        self.channel2Offset(0.0)

        # Enable capturing data from channel 1
        self.channel1State(1)
        self._ch_states[0] = True

        # Enable capturing data from channel 2
        self.channel2State(1)
        self._ch_states[1] = True

        # Select the external-trigger as start-capturing trigger:
        self.trigger1Source("EXT")
        self.trigger2Source("EXT")
        self.extTriggerType("EDGE")
        self.setup_data_path(default = True)
        self._dsp_channels = {"DDC1" : "OFF", "DDC2" : "OFF"}


        self._num_samples = 4800 # Number of samples per frame
        self._num_segs = 4 # Number of frames per repetition
        self._num_repetitions = 1 
        self._last_mem_frames_samples = (-1,-1)

    @property
    def NumSamples(self):
        return self._num_samples
    @NumSamples.setter
    def NumSamples(self, num_samples):
        self._num_samples = num_samples

    @property
    def SampleRate(self):
        return self.sample_rate()
    @SampleRate.setter
    def SampleRate(self, frequency_hertz):
        self.sample_rate(frequency_hertz)

    @property
    def NumSegments(self):
        return self._num_segs
    @NumSegments.setter
    def NumSegments(self, num_segs):
        self._num_segs = num_segs

    @property
    def NumRepetitions(self):
        return self._num_repetitions
    @NumRepetitions.setter
    def NumRepetitions(self, num_reps):
        self._num_repetitions = num_reps

    @property
    def TriggerInputEdge(self):
        return self.trigPolarity()
    @TriggerInputEdge.setter
    def TriggerInputEdge(self, pol):
        self.trigPolarity(pol)

    @property
    def AvailableChannels(self):
        return 2

    @property
    def ChannelStates(self):
        return self._ch_states
    @ChannelStates.setter
    def ChannelStates(self, ch_states):
        TABOR_DIG_CHANNEL_STATES = ['DIS', 'ENAB']
        assert len(ch_states) == 2, "There are 2 channel states that must be specified."
        for i, state in enumerate(ch_states):
            self._parent._set_cmd(':DIG:CHAN:SEL', i+1)
            self._parent._set_cmd(':DIG:CHAN:STATE', TABOR_DIG_CHANNEL_STATES[state])
            self._ch_states[i] = state
            if (self.ChannelStates[0] and self.ChannelStates[1]) :
                # If using both channels, then ensure it does the DUAL-mode setting here!
                self.acq_mode("DUAL")

    def _chan_get_cmd(self, ch, cmd):
        """
        Methods to manage switching to acive channel before running get command
        """
        #Perform channel-select
        self.activeChannel(ch)
        #Query command
        return self._parent._inst.send_scpi_query(cmd)

    def _chan_set_cmd(self, ch, cmd, value):
        """
        Method to manage switching to active channel before running set command
        """
        #Perform channel-select
        self.activeChannel(ch) #self._parent._inst.send_scpi_cmd(f':DIG:CHAN {self._active_channel}')
        #Perform command
        self._parent._inst.send_scpi_cmd(f'{cmd} {value}')

    def _allocate_frame_memory(self):
        """
        Method that allocates memory for digitizer (acquisition) 
        In DUAL mode the number of samples per frame should be a multiple of 48
        (96 for SINGLE mode)
        """
        if (self.acq_mode() == "DUAL") :
            assert (self.NumSamples % 48) == 0, \
                "In DUAL mode, number of samples must be an integer multiple of 48"
        else :
            assert (self.NumSamples % 96) == 0, \
                "In SINGLE mode, number of samples must be an integer multiple of 96"
        # Allocate four frames of self.NumSample (defaults to 48000) 
        cmd = ':DIG:ACQuire:FRAM:DEF {0},{1}'.format(self.NumRepetitions*self.NumSegments, self.NumSamples) #NOTE Unsure as to where these members are set
        self._parent._send_cmd(cmd)

        # Select the frames for the capturing 
        # (all the four frames in this example)
        capture_first, capture_count = 1, self.NumRepetitions*self.NumSegments
        cmd = ":DIG:ACQuire:FRAM:CAPT {0},{1}".format(capture_first, capture_count)
        self._parent._send_cmd(cmd)

        self._last_mem_frames_samples = (self.NumRepetitions, self.NumSegments, self.NumSamples)
        self._parent._chk_err('after allocating readout ACQ memory.')

    def get_frame_data(self):
        #Read all frames from Memory
        # 
        #Choose which frames to read (all in this example)
        self._parent._set_cmd(':DIG:DATA:SEL', 'ALL')
        #Choose what to read (only the frame-data without the header in this example)
        self._parent._set_cmd(':DIG:DATA:TYPE', 'HEAD')
        if (self.acq_mode() == "DUAL") :
            header_size = 72 # Header size taken from PG118 of manual 
        else : 
            header_size = 96 # Header size taken from PG118 of manual
        number_of_frames = self.NumSegments*self.NumRepetitions
        num_bytes = number_of_frames * header_size

        wav2 = np.zeros(num_bytes, dtype=np.uint8)
        rc = self._parent._inst.read_binary_data(':DIG:DATA:READ?', wav2, num_bytes)
        print(self._parent._get_cmd(":DIG:ACQ:STAT?")) # Perhaps check that second bit is set to 1 (all frames done)

        # Ensure all previous commands have been executed
        while (not self._parent._get_cmd('*OPC?')):
            pass
        self._parent._chk_err('in reading frame data.')

        #print(wav2)
        headerDict = {}
        trig_loc = np.zeros(number_of_frames,np.uint32)
        I_dec= np.zeros(number_of_frames,np.int32)
        Q_dec= np.zeros(number_of_frames,np.int64)
        for i in range(number_of_frames):
            idx = i* header_size
            trigPos = wav2[idx]
            gateLen = wav2[idx+1]
            minVpp = wav2[idx+2] & 0xFFFF
            maxVpp = wav2[idx+2] & 0xFFFF0000 >> 16
            timeStamp = wav2[idx+3] + wav2[idx+4] << 32
            decisionReal =  (wav2[idx+20]) + (wav2[idx+21] <<8) + \
                            (wav2[idx+22] << 16) + (wav2[idx+23] <<24) + \
                            (wav2[idx+24] << 32) + (wav2[idx+25] <<40) + \
                            (wav2[idx+26] << 48)+ (wav2[idx+27] << 56)
            decisionIm = (wav2[idx+28]) + (wav2[idx+29] << 8) + (wav2[idx+30] << 16) + (wav2[idx+31] << 24)
            state1 = wav2[idx+36]*(1 << 0)
            state2 = wav2[idx+37]*(1 << 0)
            # NOTE: they mix up I and Q here ...
            Q_dec[i]= decisionReal
            I_dec[i]= decisionIm
            headerDict["header#"] = i
            headerDict["TriggerPos"] = trigPos
            headerDict["GateLength"] = gateLen
            headerDict["MinAmp"] = minVpp
            headerDict["MaxAmp"] = maxVpp
            headerDict["MinTimeStamp"] = timeStamp
            headerDict["I"] = I_dec[i]
            headerDict["Q"] = Q_dec[i]  
            headerDict["state1"] = state1
            headerDict["state2"] = state2
            outprint = 'header# {0}\n'.format(i)
            outprint += 'TriggerPos: {0}\n'.format(trigPos)
            outprint += 'GateLength: {0}\n'.format(gateLen)
            outprint += 'Min Amp: {0}\n'.format(minVpp)
            outprint += 'Max Amp: {0}\n'.format(maxVpp)
            outprint += 'Min TimeStamp: {0}\n'.format(timeStamp)
            outprint += 'Decision: {0} + j* {1}\n'.format(decisionReal,decisionIm)
            print(outprint)
            
        dec_vals = Q_dec + 1j*I_dec # ... and fix it down here 
        return headerDict #dec_vals

    def process_block(self, block_idx, cur_processor, blocksize):
        if block_idx == 0:
            #Choose what to read (only the frame-data without the header in this example)
            self._parent._set_cmd(':DIG:DATA:TYPE', 'FRAM')
            #Choose which frames to read (One or more frames in this case)
            self._parent._set_cmd(':DIG:DATA:SEL', 'FRAM') 
            
            self._parent._set_cmd(':DIG:DATA:FRAM', f'{1},{blocksize*self.NumSegments}')

            # Get the total data size (in bytes)
            resp = self._parent._get_cmd(':DIG:DATA:SIZE?')
            # self.num_bytes = 4176*np.uint64(resp)
            # self.num_bytes = np.uint64(resp)
            # print(resp, self.num_bytes, 'hi', self._parent._get_cmd(':DIG:DATA:FRAM?'))

            # wavlen = int(self.num_bytes // 2)
            wavlen = int(blocksize*self.NumSegments*self.NumSamples)
            # print(self.num_bytes)
            #TODO : Run a check on DSP before setting up the waves, NEED TO KNOW WHAT CHANNEL AS WELL
            if (self.ddr1_store() == "DIR1") :
                wav1 = np.zeros(wavlen, dtype=np.uint16)   #NOTE!!! FOR DSP, THIS MUST BE np.uint32 - SO MAKE SURE TO SWITCH/CHANGE (uint16 otherwise)
                wav1 = wav1.reshape(blocksize, self.NumSegments, self.NumSamples)
            else :
                wav1 = np.zeros(wavlen, dtype=np.uint32)   #NOTE!!! FOR DSP, THIS MUST BE np.uint32 - SO MAKE SURE TO SWITCH/CHANGE (uint16 otherwise)
                wav1 = wav1.reshape(blocksize, self.NumSegments, self.NumSamples)

            if (self.ddr2_store() == "DIR2") :
                wav2 = np.zeros(wavlen, dtype=np.uint16)   #NOTE!!! FOR DSP, THIS MUST BE np.uint32 - SO MAKE SURE TO SWITCH/CHANGE (uint16 otherwise)
                wav2 = wav2.reshape(blocksize, self.NumSegments, self.NumSamples)
            else :
                wav2 = np.zeros(wavlen, dtype=np.uint32)   #NOTE!!! FOR DSP, THIS MUST BE np.uint32 - SO MAKE SURE TO SWITCH/CHANGE (uint16 otherwise)
                wav2 = wav2.reshape(blocksize, self.NumSegments, self.NumSamples)

            self.wav1 = wav1
            self.wav2 = wav2

        resp = self._parent._get_cmd(':DIG:DATA:SIZE?')
        num_bytes = np.uint64(resp)

        # Select the frames to read
        self._parent._set_cmd(':DIG:DATA:FRAM', f'{1+block_idx*blocksize},{blocksize}')
        if (self.ChannelStates[0]) :
            # Read from channel 1
            self._parent._set_cmd(':DIG:CHAN:SEL', 1)
            rc = self._parent._inst.read_binary_data(':DIG:DATA:READ?', self.wav1, num_bytes)
        if (self.ChannelStates[1]) :
            # read from channel 2
            self._parent._set_cmd(':DIG:CHAN:SEL', 2)
            rc = self._parent._inst.read_binary_data(':DIG:DATA:READ?', self.wav2, num_bytes)
        # Check errors
        self._parent._chk_err('after downloading the ACQ data from the FGPA DRAM.')
        sampleRates = []
        
        # Adjust Sample Rates for DDC stages if in DSP Mode
        # if (self.ddr1_store() == "DIR1") :
        #     sampleRates.append(self.SampleRate)
        # elif (self.ddc_mode() == "REAL") :
        #     # We are in non-direct REAL mode = DSP is enabled
        #     sampleRates.append(self.SampleRate/16)
        # else :
        #     sampleRates.append(self.SampleRate)

        # if (self.ddr2_store() == "DIR2") :
        #     sampleRates = sampleRates.append(self.SampleRate)
        # elif (self.ddc_mode() == "REAL") :
        #     # We are in non-direct REAL mode = DSP is enabled
        #     sampleRates.append(self.SampleRate/16)
        # else :
        #     sampleRates.append(self.SampleRate)

        #TODO: Write some blocked caching code here (like with the M4i)... 
        """ 
        ret_val = {
                    'parameters' : ['repetition', 'segment', 'sample'],
                    'data' : {
                                'CH1' : self.wav1.astype(np.int32),
                                'CH2' : self.wav2.astype(np.int32),
                                },
                    'misc' : {'SampleRates' : [self.SampleRate] * 2}  #NOTE!!! DIVIDE SAMPLERATE BY /16 IF USING DECIMATION STAGES! # sampleRates
                }
        """
        ret_val = {
                        'parameters' : ['repetition', 'segment', 'sample'],
                        'data' : {},
                        'misc' : {'SampleRates' : [self.SampleRate]*2}
                    }
        # Only return data which matches channels that are active
        if (self.ChannelStates[0]) :
            ret_val['data']['CH1'] = wav1.astype(np.int32)
        if (self.ChannelStates[1]) :
            ret_val['data']['CH2'] = wav2.astype(np.int32)

        cur_processor.push_data(ret_val)

    def convert_IQ_to_sample(self, inp_i,inp_q,size):
        """
        Convert the signed number into 12bit FIX1_11 presentation
        """
        out_i = np.zeros(inp_i.size)
        out_i = out_i.astype(np.uint32)
        
        out_q = np.zeros(inp_q.size)
        out_q = out_q.astype(np.uint32)

        max_i = np.amax(abs(inp_i))
        max_q = np.amax(abs(inp_q))
        
        max = np.maximum(max_i,max_q)
        
        if max < 1:
            max = 1
        
        inp_i = inp_i / max
        inp_q = inp_q / max
        
        M = 2**(size-1)
        A = 2**(size)
        
        for i in range(inp_i.size):
            if(inp_i[i] < 0):
                out_i[i] = int(inp_i[i]*M) + A
            else:
                out_i[i] = int(inp_i[i]*(M-1))
                
        for i in range(inp_q.size):
            if(inp_q[i] < 0):
                out_q[i] = int(inp_q[i]*M) + A
            else:
                out_q[i] = int(inp_q[i]*(M-1))

        return out_i , out_q

    def pack_kernel_data(self, ki,kq) :
        """
        Method to pack kernel data 
        """
        out_i = []
        out_q = []
        L = int(ki.size/5)
        
        b_ki = np.zeros(ki.size)
        b_kq = np.zeros(ki.size)
        kernel_data = np.zeros(L*4)
        
        b_ki = b_ki.astype(np.uint16)
        b_kq = b_kq.astype(np.uint16)
        kernel_data = kernel_data.astype(np.uint32)
        
        # convert the signed number into 12bit FIX1_11 presentation
        b_ki,b_kq = self.convert_IQ_to_sample(ki,kq,12)
        
        # convert 12bit to 15bit because of FPGA memory structure
        for i in range(L):
            s1 = (b_ki[i*5+1]&0x7) * 4096 + ( b_ki[i*5]               )
            s2 = (b_ki[i*5+2]&0x3F) * 512 + ((b_ki[i*5+1]&0xFF8) >> 3 )
            s3 = (b_ki[i*5+3]&0x1FF) * 64 + ((b_ki[i*5+2]&0xFC0) >> 6 )
            s4 = (b_ki[i*5+4]&0xFFF) *  8 + ((b_ki[i*5+3]&0xE00) >> 9 )
            out_i.append(s1)
            out_i.append(s2)
            out_i.append(s3)
            out_i.append(s4)
        
        out_i = np.array(out_i)
        
        for i in range(L):
            s1 = (b_kq[i*5+1]&0x7) * 4096 + ( b_kq[i*5]               )
            s2 = (b_kq[i*5+2]&0x3F) * 512 + ((b_kq[i*5+1]&0xFF8) >> 3 )
            s3 = (b_kq[i*5+3]&0x1FF) * 64 + ((b_kq[i*5+2]&0xFC0) >> 6 )
            s4 = (b_kq[i*5+4]&0xFFF) *  8 + ((b_kq[i*5+3]&0xE00) >> 9 )
            out_q.append(s1)
            out_q.append(s2)
            out_q.append(s3)
            out_q.append(s4)

        out_q = np.array(out_q)

        fout_i = np.zeros(out_i.size)
        fout_q = np.zeros(out_q.size)

        for i in range(out_i.size):
            if(out_i[i] >16383):
                fout_i[i] = out_i[i] - 32768
            else:
                fout_i[i] = out_i[i]

        for i in range(out_q.size):
            if(out_q[i] >16383):
                fout_q[i] = out_q[i] - 32768
            else:
                fout_q[i] = out_q[i]
        
        for i in range(L*4):
            kernel_data[i] = out_q[i]*(1 << 16) + out_i[i]
        sim_kernel_data = []

        for i in range(kernel_data.size):
            sim_kernel_data.append(hex(kernel_data[i])[2:])

        return kernel_data

    def setup_data_path(self, **kwargs) :
        """
        Method to setup datapath of the acquisition
        takes in kwargs to setu data path
        default input resets all variables to their defaults
        @arg ddc_mode: "COMP" or "REAL" (Default "")
        @arg acq_mode: "SING" or "DUAL" (Default "")
        @arg default: true or false (Default false)
        @arg ddr1_store: "DIR<N>"{1,2} or "DSP<N>"{1,2,3,4} or "FFTI" or "FFTO" (Default "DIR1")
        @arg ddr2_store: "DIR<N>"{1,2} or "DSP<N>"{1,2,3,4} or "FFTI" or "FFTO" (Default "DIR1")
        """
        # Check if default is set
        # TODO: Better way to handle kwargs so there is no need to use nested ifs
        if "default" in kwargs :
            if kwargs["default"] == True :
                # Set Default Values
                self.acq_mode("DUAL")
                self.ddc_mode("REAL")
                self.ddr1_store("DIR1")
                self.ddr2_store("DIR2")
                return

        # Assign variables
        self.acq_mode(kwargs.get("acq_mode", self.acq_mode()))
        self.ddc_mode(kwargs.get("ddc_mode", self.ddc_mode()))
        self.ddr1_store(kwargs.get("ddr1_store", self.ddr1_store()))
        self.ddr2_store(kwargs.get("ddr2_store", self.ddr2_store()))
        # self.ddc_mode("COMP")
        # self.ddc_mode("REAL")
        # If in Complex mode, storage options are limited 
        # TODO: confirm if it will set to something allowed automatically
        # if (self.ddc_mode() == "COMP") :
        #     self.ddr1_store(kwargs.get("ddr1_store", self.ddr1_store()))
        #     self.ddr2_store(kwargs.get("ddr2_store", self.ddr2_store()))
        # else :
        #     self.ddr1_store(kwargs.get("ddr1_store", self.ddr1_store()))
        #     self.ddr2_store(kwargs.get("ddr2_store", self.ddr2_store()))

    def iq_kernel(self, coefficients, fs, flo=400e6, kl=10240):
        """
        Method to sythesise an IQ kernel for frequency extraction
        """
        TAP = coefficients.size
        # print('loaded {0} TAP filter from {1}'.format(TAP,coe_file_path))
        res = 10
        L = res * math.ceil(kl / res)
        k = np.ones(L+TAP)
        
        pi = math.pi
        ts = 1 / fs
        t = np.linspace(0, L*ts, L, endpoint=False)
        
        loi = np.cos(2 * pi * flo * t)
        loq = -(np.sin(2 * pi * flo * t))
        
        k_i = np.zeros(L)
        k_q = np.zeros(L)
        
        for l in range(L):
            b = 0
            for n in range(TAP):
                b += k[l+n]*coefficients[n]
            k_q[l] = loq[l] * b
            k_i[l] = loi[l] * b
        
        print('sigma bn = {0}'.format(b))
        return(k_i,k_q)


    def setup_kernel(self, path, coefficients, flo, kl=10240) :
        """
        Method to setup kernel on real path
        @param path:
        @param coefficients:
        @param flo
        @param kl
        """
        valid_paths = ["DBUG", "IQ4", "IQ5", "IQ6", "IQ7"]
        if path not in valid_paths :
            print("Not a valid iq demodulation kernel to program, must be one of: 'DBUG' 'IQ4' 'IQ5' 'IQ6' 'IQ7'")
            return
        self.iq_demod(path)
        ki,kq = self.iq_kernel(coefficients, flo=flo, fs = self.SampleRate, kl=kl)
        #ki = np.linspace(0,1,ki.size)
        #kq = np.linspace(0,-1,ki.size)
        mem = self.pack_kernel_data(ki,kq)
        self._parent._inst.write_binary_data(':DSP:IQD:KER:DATA', mem)
        resp = self._parent._inst.send_scpi_query(':SYST:ERR?')
        print(resp)


    def setup_filter(self, filter_channel, filter_array, **kwargs) :
        """
        Method to set coefficients for specific FIR filter on Tabor
        @param filter_channel:
        """
        valid_real_channels = ["DBUQI", "DBUGQ"]
        valid_complex_channels = ["I1", "Q1", "I2", "Q2"]
        # Check that the requested block is valid for the current ddc mode
        # NOTE: could remove this check and rely on user to know what blocks are being used when
        print("DDC mode is: ", self.ddc_mode())
        if (self.ddc_mode() == "REAL" and filter_channel in valid_real_channels) :
            self.fir_block(filter_channel)
        elif (self.ddc_mode() == "COMP" and filter_channel in valid_complex_channels) :
            self.fir_block(filter_channel)
        else :
            print("Not a vaild filter channel for current DDC mode")

        # Check array size is valid
        if (len(filter_array) > int(self._parent._inst.send_scpi_query(':DSP:FIR:LENG?'))) :
            print("filter array contains too many coefficients, limit is {0}".format(self._parent._inst.send_scpi_query(':DSP:FIR:LENG?')))
            return

        # dsp decision frame
        # TODO: what is the frame size of the calculation
        self._parent._inst.send_scpi_cmd(':DSP:DEC:FRAM {0}'.format(1024))
        resp = self._parent._inst.send_scpi_query(':SYST:ERR?')
        print(resp)

        # Load in filter coefficients
        for i in range(0, len(filter_array)) :
            self._parent._inst.send_scpi_cmd(':DSP:FIR:COEF {},{}'.format(i, filter_array[i]))
            
        # self._parent._inst.send_scpi_cmd(':DSP:IQD:SEL IQ4')           # DBUG | IQ4 | IQ5 | IQ6 | IQ7
        # self._parent._inst.send_scpi_cmd(':DSP:IQD:KER:DATA', mem)
        # resp =  self._parent._inst.send_scpi_query(':SYST:ERR?')
        # print(resp)

        # define decision DSP1 path SVM
        # self._parent._inst.send_scpi_cmd(':DSP:DEC:IQP:SEL DSP1')
        # self._parent._inst.send_scpi_cmd(':DSP:DEC:IQP:OUTP SVM')
        # self._parent._inst.send_scpi_cmd(':DSP:DEC:IQP:LINE 1,-0.625,-5')
        # self._parent._inst.send_scpi_cmd(':DSP:DEC:IQP:LINE 2,1.0125,0.5')
        # self._parent._inst.send_scpi_cmd(':DSP:DEC:IQP:LINE 3,0,0')

    def get_data(self, **kwargs):
        self.blocksize(self.NumRepetitions)
        #TODO:
        #Currently:
        #  - It starts reading. Once a block-size B has been read, it stops checking
        #  - Then it reads B frames and processes them. However, it does not process the case where Reps = q*B + r with r=/=0
        #  - Also, it SHOULD CHECK whether the Tabor has indeed captured m*B frames when processing block m. It assumes that the processing overhead
        #    exceeds the capture time - MAKE SURE TO IMPLEMENT THIS. For now, the hack is to set B = R
        # question is just in the above, it says it reads a block size B, then reads B frames, just a bit confused by terminology, as a thought there would be a certain
        # number of frames within a block?
        #Tentative yes. The processing mostly operates on repetitions. So you usually feed the processor full repetitions 
        # So basically a Repetition is a collection of segemtns and samples. You opt to measure a total of Reps repetitions. RN wanted to take it in blocks
        # of B repetitions to then process - except he didn't check all edge cases and forgot about what is highlighted above...
        # I think the idea is that you want to choose B optimally such that it doesn't use up too much RAM and processes everything in a timely manner...
        """
        Acquisitions are defined in terms of sampling rate, record length (number of samples to be 
        captured for each trigger event), and position (the location of the closest sample to the trigger 
        event). Multiple frame acquisitions (or Multi-Frame) require the definition of the number of 
        frames to be captured.
        """
        blocksize = min(self.blocksize(), self.NumRepetitions)

        assert self.NumSamples % 48 == 0, "The number of samples must be divisible by 48 if in DUAL mode."

        cur_processor = kwargs.get('data_processor', None)

        if self._last_mem_frames_samples[0] != self.NumRepetitions or self._last_mem_frames_samples[1] != self.NumSegments or self._last_mem_frames_samples[2] != self.NumSamples:
            self._allocate_frame_memory()

        # Clean memory 
        self._parent._send_cmd(':DIG:ACQ:ZERO:ALL 0') # NOTE: This didnt have the '0' argument originally

        self._parent._chk_err('after clearing memory.')

        self._parent._chk_err('before')
        self._parent._set_cmd(':DIG:INIT', 'ON')
        self._parent._chk_err('dig:on')
        
        #Poll for status bit
        loopcount = 0
        captured_frame_count = 0
        while captured_frame_count < blocksize: #NOTE : WHy is this being compared to repititions and not repititions * numFrames
            resp = self._parent._get_cmd(":DIG:ACQuire:FRAM:STATus?")
            resp_items = resp.split(',')
            captured_frame_count = int(resp_items[3])
            done = int(resp_items[1])
            #print("{0}. {1}".format(done, resp_items))
            loopcount += 1
            if loopcount > 100000 and captured_frame_count == 0:    #As in nothing captured over 1000 check-loops...
                #print("No Trigger was detected")
                assert False, "No trigger detected during the acquisiton sniffing window."
                done = 1

        # If processor is supplied apply it
        if cur_processor:
            self.process_block(0, cur_processor, blocksize)
            block_idx = 1
            while block_idx*blocksize < self.NumRepetitions*self.NumSegments: # NOTE : some strange logic, perhaps tied to the logic above
                self.process_block(block_idx, cur_processor, blocksize)
                block_idx += 1
            return cur_processor.get_all_data()
        else:
            # No processor supplied
            done = 0
            while not done:
                done = int(self._parent._get_cmd(":DIG:ACQuire:FRAM:STATus?").split(',')[3])
            # Stop the digitizer's capturing machine (to be on the safe side)
            self._parent._set_cmd(':DIG:INIT', 'OFF')

            self._parent._chk_err('after actual acquisition.')
            #Choose which frames to read (all in this example)
            self._parent._set_cmd(':DIG:DATA:SEL', 'ALL')
            #Choose what to read (only the frame-data without the header in this example)
            self._parent._set_cmd(':DIG:DATA:TYPE', 'FRAM')
            
            # Get the total data size (in bytes)
            resp = self._parent._get_cmd(':DIG:DATA:SIZE?')
            num_bytes = np.uint64(resp)
            #print(num_bytes, 'hi', self._parent._get_cmd(':DIG:DATA:FRAM?'))

            wavlen = int(num_bytes // 2)
            fakeNumSamples = num_bytes / (self.NumSegments*2)
            # TODO: NEED TO CHANGE DATATYPE BASED ON DSP MODE # NOTE: WE NO LONGER HAVE TO?!?!?! WHATS GOING ON HERE
            if (self.ChannelStates[0]) :
                if (self.ddr1_store() == "DIR1") :
                    wav1 = np.zeros(wavlen, dtype=np.uint16)   #NOTE!!! FOR DSP, THIS MUST BE np.uint32 - SO MAKE SURE TO SWITCH/CHANGE (uint16 otherwise)
                    wav1 = wav1.reshape(self.NumRepetitions, self.NumSegments, int(fakeNumSamples))
                else :
                    wav1 = np.zeros(wavlen, dtype=np.uint16)   #NOTE!!! FOR DSP, THIS MUST BE np.uint32 - SO MAKE SURE TO SWITCH/CHANGE (uint16 otherwise)
                    wav1 = wav1.reshape(self.NumRepetitions, self.NumSegments, int(fakeNumSamples))
            #if (self.ChannelStates[1]) :
            if (self.ddr2_store() == "DIR2") :
                wav2 = np.zeros(wavlen, dtype=np.uint16)   #NOTE!!! FOR DSP, THIS MUST BE np.uint32 - SO MAKE SURE TO SWITCH/CHANGE (uint16 otherwise)
                wav2 = wav2.reshape(self.NumRepetitions, self.NumSegments, int(fakeNumSamples)) # self.NumSamples
            else :
                wav2 = np.zeros(wavlen, dtype=np.uint16)   #NOTE!!! FOR DSP, THIS MUST BE np.uint32 - SO MAKE SURE TO SWITCH/CHANGE (uint16 otherwise)
                wav2 = wav2.reshape(self.NumRepetitions, self.NumSegments, int(fakeNumSamples)) # self.NumSamples
        
            # Ensure all previous commands have been executed
            while (not self._parent._get_cmd('*OPC?')):
                pass
            if (self.ChannelStates[0]) :
                # Read from channel 1
                self._parent._set_cmd(':DIG:CHAN:SEL', 1)
                rc = self._parent._inst.read_binary_data(':DIG:DATA:READ?', wav1, num_bytes)
                # Ensure all previous commands have been executed
                while (not self._parent._get_cmd('*OPC?')):
                    pass
            if (self.ChannelStates[1]) :
                # read from channel 2
                self._parent._set_cmd(':DIG:CHAN:SEL', 2)
                rc = self._parent._inst.read_binary_data(':DIG:DATA:READ?', wav2, num_bytes)
                # Ensure all previous commands have been executed
                while (not self._parent._get_cmd('*OPC?')):
                    pass
            # Check errors
            self._parent._chk_err('after downloading the ACQ data from the FGPA DRAM.')

            #TODO: Write some blocked caching code here (like with the M4i)...
            """
            ret_val = {
                        'parameters' : ['repetition', 'segment', 'sample'],
                        'data' : {
                                    'CH1' : wav1.astype(np.int32),
                                    'CH2' : wav2.astype(np.int32),
                                    },
                        'misc' : {'SampleRates' : [self.SampleRate]*2}
                    }
            """
            ret_val = {
                        'parameters' : ['repetition', 'segment', 'sample'],
                        'data' : {},
                        'misc' : {'SampleRates' : [self.SampleRate]*2}
                    }
            # Only return data which matches channels that are active
            if (self.ChannelStates[0]) :
                ret_val['data']['CH1'] = wav1.astype(np.int32)
            if (self.ChannelStates[1]) :
                ret_val['data']['CH2'] = wav2.astype(np.int32)
            return ret_val

class Tabor_P2584M(Instrument):
    def __init__(self, name, pxi_chassis: int,  pxi_slot: int, **kwargs):
        super().__init__(name, **kwargs) #No address...
        #Currently Tabor doesn't seem to use pxi_chassis in their newer drivers - curious...

        # Use lib_dir_path = None 
        # for default location (C:\Windows\System32)
        # Change it only if you know what you are doing
        lib_dir_path = None
        self._admin = TepAdmin(lib_dir_path)

        self._inst = self._admin.open_instrument(slot_id=pxi_slot)
        assert self._inst != None, "Failed to load the Tabor AWG instrument - check slot ID perhaps."

        #Tabor's driver will print error messages if any are present after every command - it is an extra query, but provides security
        self._inst.default_paranoia_level = 2

        #Get HW options
        # self._inst.send_scpi_query("*OPT?")
        #Reset - must!
        self._inst.send_scpi_cmd( "*CLS")
        self._inst.send_scpi_cmd( "*RST")

        #ENSURE THAT THE REF-IN IS CONNECTED TO Rb Oven if using EXT 10MHz source!
        self.add_parameter(
            'ref_osc_src', label='Reference Oscillator Source',
            get_cmd=partial(self._get_cmd, ':ROSC:SOUR?'),
            set_cmd=partial(self._set_cmd, ':ROSC:SOUR'),
            val_mapping={'INT': 'INT', 'EXT': 'EXT'}
            )
        self.add_parameter(
            'ref_osc_freq', label='Reference Oscillator Frequency', unit='Hz',
            get_cmd=partial(self._get_cmd, ':ROSC:FREQ?'),
            set_cmd=partial(self._set_cmd, ':ROSC:FREQ'),
            val_mapping={10e6: '10M', 100e6: '100M'}
            )

        self._debug_logs = ''
        self._debug = True

        #Add the AWG and ACQ submodules to cordon off the different sub-instrument properties...
        self.add_submodule('AWG', TaborP2584M_AWG(self))    #!!!NOTE: If this name is changed from 'AWG', make sure to change it in the TaborP2584M_AWG class initializer!
        self.add_submodule('ACQ', TaborP2584M_ACQ(self))    #!!!NOTE: If this name is changed from 'ACQ', make sure to change it in the TaborP2584M_ACQ class initializer!

    def close(self):
        #Override QCoDeS function to ensure proper resource release
        #close connection
        self._inst.close_instrument()
        self._admin.close_inst_admin()
        super().close()



    def _send_cmd(self, cmd):
        self._inst.send_scpi_cmd(cmd)
    
    def _get_cmd(self, cmd):
        if self._debug:
            self._debug_logs += cmd + '\n'
        return self._inst.send_scpi_query(cmd)
    def _set_cmd(self, cmd, value):
        if self._debug:
            self._debug_logs += f"{cmd} {value}\n"
        self._inst.send_scpi_cmd(f"{cmd} {value}")
    
    def _chk_err(self, msg):
        resp = self._get_cmd(':SYST:ERR?')
        resp = resp.rstrip()
        assert resp.startswith('0'), 'ERROR: "{0}" {1}.'.format(resp, msg)

