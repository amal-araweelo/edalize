import multiprocessing
import os
import logging

from edalize.edatool import Edatool

logger = logging.getLogger(__name__)

CONFIG_MK_TEMPLATE = """#Auto generated by Edalize

TOP_MODULE        := {top_module}
VC_FILE           := {vc_file}
VERILATOR_OPTIONS := {verilator_options}
MAKE_OPTIONS      := {make_options}
"""

MAKEFILE_TEMPLATE = """#Auto generated by Edalize

include config.mk

#Assume a local installation if VERILATOR_ROOT is set
ifeq ($(VERILATOR_ROOT),)
VERILATOR ?= verilator
else
VERILATOR ?= $(VERILATOR_ROOT)/bin/verilator
endif

V$(TOP_MODULE): V$(TOP_MODULE).mk
	$(MAKE) $(MAKE_OPTIONS) -f $<

V$(TOP_MODULE).mk:
	$(VERILATOR) -f $(VC_FILE) $(VERILATOR_OPTIONS)
"""

class Verilator(Edatool):

    _description = "Verilator is the fastest free Verilog HDL simulator, and outperforms most commercial simulators"
    tool_options = {'members' : {'mode' : 'String',
                                 'cli_parser' : 'String'},
                    'lists'   : {'libs' : 'String',
                                 'verilator_options' : 'String'},
                                 'make_options': 'String'}

    argtypes = ['cmdlinearg', 'plusarg', 'vlogdefine', 'vlogparam']

    @classmethod
    def get_doc(cls, api_ver):
        if api_ver == 0:
            return {'description' : cls._description,
                    'members' : [
                        {'name' : 'mode',
                         'type' : 'String',
                         'desc' : 'Select compilation mode. Legal values are *cc* for C++ testbenches, *sc* for SystemC testbenches or *lint-only* to only perform linting on the Verilog code'},
                        {'name' : 'cli_parser',
                         'type' : 'String',
                         'desc' : 'Select whether FuseSoC should handle command-line arguments (*managed*) or if they should be passed directly to the verilated model (*raw*). Default is *managed*'}],
                    'lists' : [
                        {'name' : 'libs',
                         'type' : 'String',
                         'desc' : 'Extra libraries for the verilated model to link against'},
                        {'name' : 'verilator_options',
                         'type' : 'String',
                         'desc' : 'Additional options for verilator'},
                        {'name' : 'make_options',
                         'type' : 'String',
                         'desc' : 'Additional arguments passed to make when compiling the simulation. This is commonly used to set OPT/OPT_FAST/OPT_SLOW.'},
                        ]}

    def _managed_parser(self):
        return not 'cli_parser' in self.tool_options or self.tool_options['cli_parser'] == 'managed'

    def configure_pre(self, args):
        if self._managed_parser():
            self.parse_args(args, self.argtypes)

    def configure_main(self):
        if not self.toplevel:
            raise RuntimeError("'" + self.name + "' miss a mandatory parameter 'top_module'")

        self._write_config_files()

    def _write_config_files(self):
        #Future improvement: Separate include directories of c and verilog files
        incdirs = set()
        src_files = []

        (src_files, incdirs) = self._get_fileset_files()

        self.verilator_file = self.name + '.vc'

        with open(os.path.join(self.work_root,self.verilator_file),'w') as f:
            f.write('--Mdir .\n')
            modes = ['sc', 'cc', 'lint-only']

            #Default to cc mode if not specified
            if not 'mode' in self.tool_options:
                self.tool_options['mode'] = 'cc'

            if self.tool_options['mode'] in modes:
                f.write('--'+self.tool_options['mode']+'\n')
            else:
                _s = "Illegal verilator mode {}. Allowed values are {}"
                raise RuntimeError(_s.format(self.tool_options['mode'],
                                             ', '.join(modes)))
            if 'libs' in self.tool_options:
                for lib in self.tool_options['libs']:
                    f.write('-LDFLAGS {}\n'.format(lib))
            for include_dir in incdirs:
                f.write("+incdir+" + include_dir + '\n')
                f.write("-CFLAGS -I{}\n".format(include_dir))
            opt_c_files = []
            for src_file in src_files:
                if src_file.file_type.startswith("systemVerilogSource") or src_file.file_type.startswith("verilogSource"):
                    f.write(src_file.name + '\n')
                elif src_file.file_type in ['cppSource', 'systemCSource', 'cSource']:
                    opt_c_files.append(src_file.name)
                elif src_file.file_type in ['user']:
                    pass
            f.write('--top-module {}\n'.format(self.toplevel))
            f.write('--exe\n')
            f.write('\n'.join(opt_c_files))
            f.write('\n')
            f.write(''.join(['-G{}={}\n'.format(key, self._param_value_str(value)) for key, value in self.vlogparam.items()]))
            f.write(''.join(['-D{}={}\n'.format(key, self._param_value_str(value)) for key, value in self.vlogdefine.items()]))

        with open(os.path.join(self.work_root, 'Makefile'), 'w') as makefile:
            makefile.write(MAKEFILE_TEMPLATE)

        if 'verilator_options' in self.tool_options:
            verilator_options = ' '.join(self.tool_options['verilator_options'])
        else:
            verilator_options = ''

        if 'make_options' in self.tool_options:
            make_options = ' '.join(self.tool_options['make_options'])
        else:
            make_options = ''

        with open(os.path.join(self.work_root, 'config.mk'), 'w') as config_mk:
            config_mk.write(CONFIG_MK_TEMPLATE.format(
                top_module        = self.toplevel,
                vc_file           = self.verilator_file,
                verilator_options = verilator_options,
                make_options      = make_options))

    def build_main(self):
        logger.info("Building simulation model")
        if not 'mode' in self.tool_options:
            self.tool_options['mode'] = 'cc'

        # Do parallel builds with <number of cpus> * 2 jobs.
        make_job_count = multiprocessing.cpu_count() * 2
        args = ['-j', str(make_job_count)]

        if self.tool_options['mode'] == 'lint-only':
            args.append('V'+self.toplevel+'.mk')
        _s = os.path.join(self.work_root, 'verilator.{}.log')
        self._run_tool('make', args)

    def run_pre(self, args):
        #Default to cc mode if not specified
        if not 'mode' in self.tool_options:
            self.tool_options['mode'] = 'cc'
        if self.tool_options['mode'] == 'lint-only':
            return
        if self._managed_parser():
            self.parse_args(args, self.argtypes)

            self.args = []
            for key, value in self.plusarg.items():
                self.args += ['+{}={}'.format(key, self._param_value_str(value))]
            for key, value in self.cmdlinearg.items():
                self.args += ['--{}={}'.format(key, self._param_value_str(value))]
        else:
            self.args = args

        if 'pre_run' in self.hooks:
            self._run_scripts(self.hooks['pre_run'])

    def run_main(self):
        if self.tool_options['mode'] == 'lint-only':
            return
        logger.info("Running simulation")
        self._run_tool('./V' + self.toplevel, self.args)
