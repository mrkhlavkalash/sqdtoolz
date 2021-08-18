from sqdtoolz.Experiment import*
from sqdtoolz.HAL.WaveformGeneric import*
from sqdtoolz.HAL.WaveformSegments import*
from sqdtoolz.Utilities.DataFitting import*

class ExpRamseyGE(Experiment):
    def __init__(self, name, expt_config, wfmt_qubit_drive, range_waits, SPEC_qubit, iq_indices = [0,1], **kwargs):
        super().__init__(name, expt_config)

        self._iq_indices = iq_indices
        self._wfmt_qubit_drive = wfmt_qubit_drive
        
        self._range_waits = range_waits
        self._post_processor = kwargs.get('post_processor', None)
        self._param_ramsey_frequency = kwargs.get('param_ramsey_frequency', None)
        self._param_ramsey_decay_time = kwargs.get('param_ramsey_decay_time', None)

        self._SPEC_qubit = SPEC_qubit

        #Calculate default load-time via T1 of qubit or default to 40e-6
        def_load_time = self._SPEC_qubit['GE T1'].Value * 4
        if def_load_time == 0:
            def_load_time = 40e-6
        #Override the load-time if one is specified explicitly
        self.load_time = kwargs.get('load_time', 40e-6)

        #Calculate tipping amplitude
        def_tip_ampl = self._SPEC_qubit['GE X-Gate Amplitude'].Value * 0.5
        #Override the tip-amplitude if one is specified explicitly
        self.tip_ampl = kwargs.get('tip_amplitude', def_tip_ampl)
        assert self.tip_ampl != 0, "Tip-amplitude is zero. Either supply a tip_amplitude or have \'GE X-Gate Amplitude\' inside the qubit SPEC to be non-zero (e.g. run Rabi first?)."

        #Calculate tipping time
        def_tip_time = self._SPEC_qubit['GE X-Gate Time'].Value
        #Override the tip-time if one is specified explicitly
        self.tip_time = kwargs.get('tip_time', def_tip_time)
        assert self.tip_time != 0, "Tip-time is zero. Either supply a tip_time or have \'GE X-Gate Time\' inside the qubit SPEC to be non-zero (e.g. run Rabi first?)."

        self.readout_time = kwargs.get('readout_time', 2e-6)
    
    def _run(self, file_path, sweep_vars=[], **kwargs):
        assert len(sweep_vars) == 0, "Cannot specify sweeping variables in this experiment."

        self._expt_config.init_instruments()

        wfm = WaveformGeneric(['qubit'], ['readout'])
        wfm.set_waveform('qubit', [
            WFS_Constant("SEQPAD", None, -1, 0.0),
            WFS_Constant("init", None, self.load_time, 0.0),
            WFS_Gaussian("tip", self._wfmt_qubit_drive.apply(phase=0), self.tip_time, self.tip_ampl),
            WFS_Constant("wait", None, 1e-9, 0.0),
            WFS_Gaussian("untip", self._wfmt_qubit_drive.apply(), self.tip_time, self.tip_ampl),
            WFS_Constant("pad", None, 5e-9, 0.0),
            WFS_Constant("read", None, self.readout_time, 0.0)
        ])
        wfm.set_digital_segments('readout', 'qubit', ['read'])
        self._temp_vars = self._expt_config.update_waveforms(wfm, [('Wait Time', 'qubit', 'wait', 'Duration')] )

        sweep_vars = [(self._temp_vars[0], self._range_waits)]

        kwargs['skip_init_instruments'] = True

        self._cur_param_name = self._temp_vars[0].Name
        return super()._run(file_path, sweep_vars, **kwargs)

    def _post_process(self, data):
        if self._post_processor:
            self._post_processor.push_data(data)
            data = self._post_processor.get_all_data()
        
        assert self._cur_param_name in data.param_names, "Something went wrong and the sweeping parameter disappeared in the data processing?"
        cur_sweep_ind = data.param_names.index(self._cur_param_name)

        arr = data.get_numpy_array()
        data_x = data.param_vals[cur_sweep_ind]
        data_y = np.sqrt(arr[:,self._iq_indices[0]]**2 + arr[:,self._iq_indices[1]]**2)

        dfit = DFitSinusoid()
        dpkt = dfit.get_fitted_plot(data_x, data_y, 'Drive Amplitude', 'IQ Amplitude')

        #Commit to parameters...
        if self._param_ramsey_frequency:
            self._param_ramsey_frequency.Value = dpkt['frequency']
        if self._param_ramsey_decay_time:
            self._param_ramsey_decay_time.Value = 1.0 / dpkt['decay_rate']

        # if self._transition == 'GE':
        #     self._SPEC_qubit['GE X-Gate Amplitude'].Value = 0.5/self._param_rabi_frequency
        #     self._SPEC_qubit['GE X-Gate Time'].Value = self.drive_time
        # else:
        #     self._SPEC_qubit['EF X-Gate Amplitude'].Value = 0.5/self._param_rabi_frequency
        #     self._SPEC_qubit['EF X-Gate Time'].Value = self.drive_time

        print(dpkt)
        dpkt['fig'].show()
        
