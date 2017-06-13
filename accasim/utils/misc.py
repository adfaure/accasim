"""
MIT License

Copyright (c) 2017 cgalleguillosm

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import re
import os
import logging
import random
import json
from datetime import datetime
import time
from lib2to3.pgen2.tokenize import group
from threading import Timer, Thread
from inspect import getouterframes, currentframe
import functools
import inspect
from collections import namedtuple, Mapping
from _collections import deque
from math import sqrt
from bisect import bisect, bisect_left, bisect_right
import socket
from sys import platform as _platform, exit as _exit
import threading, json
from abc import ABC, abstractmethod
from _functools import reduce
from itertools import islice
from builtins import int, str
import sys

_swf_int_pattern = ('\s*(?P<{}>[-+]?\d+)', int)
_swf_float_pattern = ('\s*(?P<{}>[-+]?\d+\.\d+|[-+]?\d+)', float)
_swf_avoid_regexps = [r'^;.*']
default_swf_parse_config = (
    {
        'job_number': _swf_int_pattern,
        'submit_time': _swf_int_pattern,
        'wait_time': _swf_int_pattern,
        'duration': _swf_int_pattern,
        'allocated_processors': _swf_int_pattern,
        'avg_cpu_time': _swf_float_pattern,
        'used_memory': _swf_int_pattern,
        'requested_number_processors': _swf_int_pattern,
        'requested_time': _swf_int_pattern,
        'requested_memory': _swf_int_pattern,
        'status': _swf_int_pattern,
        'user_id': _swf_int_pattern,
        'group_id': _swf_int_pattern,
        'executable_number': _swf_int_pattern,
        'queue_number': _swf_int_pattern,
        'partition_number': _swf_int_pattern,
        'preceding_job_number': _swf_int_pattern,
        'think_time_prejob': _swf_int_pattern
    }, _swf_avoid_regexps)

default_swf_mapper = {
    'job_number': 'job_id',
    'submit_time': 'queued_time',
    'requested_time': 'expected_duration'
}

def default_sorting_function(obj1, obj2, avoid_data_tokens=[';']): 
    if obj1[0] in avoid_data_tokens or obj2[0] in avoid_data_tokens:
        return 1
    return default_sorted_attribute(obj1) - default_sorted_attribute(obj2) 

def default_sorted_attribute(workload_line, attr='submit_time', converter=None):
    # print('wl: ', workload_line)
    value = workload_parser(workload_line, attr)[attr]
    if converter:
        return converter(value)
    return value

def workload_parser(workload_line, attrs=None, avoid_data_tokens=[';']):
    """ 
        Attributes of each workload line in a SWF format (separated by space):
        
        1. job_number -- a counter field, starting from 1.
        2. submit_time -- in seconds. The earliest time the log refers to is zero, and is usually the submittal time of the first job. The lines in the log are sorted by ascending submittal times. It makes sense for jobs to also be numbered in this order.
        3. wait_time -- in seconds. The difference between the job's submit time and the time at which it actually began to run. Naturally, this is only relevant to real logs, not to models.
        4. duration -- in seconds. The wall clock time the job was running (end time minus start time).
        5. allocated_processors -- an integer. In most cases this is also the number of processors the job uses; if the job does not use all of them, we typically don't know about it.
        6. avg_cpu_time -- Time Used for both user and system, in seconds. This is the average over all processors of the CPU time used, and may therefore be smaller than the wall clock runtime. If a log contains the total CPU time used by all the processors, it is divided by the number of allocated processors to derive the average.
        7. used_memory -- in kilobytes. This is again the average per processor.
        8. requested_number_processors --- Requested Number of Processors.
        9. requested_time -- This can be either runtime (measured in wallclock seconds), or average CPU time per processor (also in seconds) -- the exact meaning is determined by a header comment. In many logs this field is used for the user runtime estimate (or upper bound) used in backfilling. If a log contains a request for total CPU time, it is divided by the number of requested processors.
        10. requested_memory -- Requested memory in kilobytes per processor.
        11. status -- 1 if the job was completed, 0 if it failed, and 5 if cancelled. If information about chekcpointing or swapping is included, other values are also possible. See usage note below. This field is meaningless for models, so would be -1.
        12. user_id -- a natural number, between one and the number of different users.
        13. group_id -- a natural number, between one and the number of different groups. Some systems control resource usage by groups rather than by individual users.
        14. executable_number -- a natural number, between one and the number of different applications appearing in the workload. in some logs, this might represent a script file used to run jobs rather than the executable directly; this should be noted in a header comment.
        15. queue_number -- a natural number, between one and the number of different queues in the system. The nature of the system's queues should be explained in a header comment. This field is where batch and interactive jobs should be differentiated: we suggest the convention of denoting interactive jobs by 0.
        16. partition_number -- a natural number, between one and the number of different partitions in the systems. The nature of the system's partitions should be explained in a header comment. For example, it is possible to use partition numbers to identify which machine in a cluster was used.
        17. preceding_job_number -- this is the number of a previous job in the workload, such that the current job can only start after the termination of this preceding job. Together with the next field, this allows the workload to include feedback as described below.
        18. think_time_prejob -- this is the number of seconds that should elapse between the termination of the preceding job and the submittal of this one.
    """ 
    if workload_line[0] in avoid_data_tokens:
        return workload_line
    _common_int_pattern = ('\s*(?P<{}>[-+]?\d+)', int)
    _common_float_pattern = ('\s*(?P<{}>[-+]?\d+\.\d+|[-+]?\d+)', float)
    _dict = {
        'job_number': _common_int_pattern,
        'submit_time': _common_int_pattern,
        'wait_time': _common_int_pattern,
        'duration': _common_int_pattern,
        'allocated_processors': _common_int_pattern,
        'avg_cpu_time': _common_float_pattern,
        'used_memory': _common_int_pattern,
        'requested_number_processors': _common_int_pattern,
        'requested_time': _common_int_pattern,
        'requested_memory': _common_int_pattern,
        'status': _common_int_pattern,
        'user_id': _common_int_pattern,
        'group_id': _common_int_pattern,
        'executable_number': _common_int_pattern,
        'queue_number': _common_int_pattern,
        'partition_number': _common_int_pattern,
        'preceding_job_number': _common_int_pattern,
        'think_time_prejob': _common_int_pattern
    }
    _sequence = _dict.keys() if not attrs else ((attrs,) if isinstance(attrs, str) else attrs)
    reg_exp = r''
    for _key in _sequence:
        reg_exp += _dict[_key][0].format(_key)
    p = re.compile(reg_exp)
    _matches = p.match(workload_line)
    # value_func = lambda line, _dict, key: 
    _dict_line = _matches.groupdict()
    return {key:_dict[key][1](_dict_line[key]) for key in _sequence} 
    

def sort_file(input_filepath, lines=None, sort_function=default_sorting_function, avoid_data_tokens=[';'], output_filepath=None):
    """
        The input file for the simulator must be sorted by submit time. It modifies the file input file, 
        or also can be saved to a new one if the output_filepath arg is defined.
          
        :param input_filepath: Input workload file
        :param lines: Number of lines to be read. It includes all lines from the begining of the file. 
        :param sort_function: (Optional) The function that sorts the file by submit time. The user is responsable 
                to define the correct function. If a workload with SWF format is used, by default 
                default_sorting_function (SWF workload) is used.
        :param avoid_data_tokens: (Optional) By default avoid to modify comment lines of SWF workload.      
        :param output_filepath: (Optional) The sorted data is saves into another file (this filepath). 
                It will not content the lines that begin with tokens of the avoid_data_tokens var.
        
        :return: A list of queued time points.  
    """
    assert(callable(sort_function))
    logging.debug('Sorting File: %s ' % (input_filepath))
    with open(input_filepath) as f:
        sorted_file = list(f if not lines else islice(f, lines))
        sorted_file .sort(
            key=cmp_to_key(sort_function)
        )
    if output_filepath is None:
        output_filepath = input_filepath
    logging.debug("Writing sorted file to %s" % (output_filepath))
    queued_times = sorted_list()
    with open(output_filepath, 'w') as f:
        for line in sorted_file:
            if line[0] in avoid_data_tokens:
                f.write(line)
                continue
            _line = workload_parser(line)
            if int(_line['requested_number_processors']) == -1 and int(_line['allocated_processors']) == -1 or int(_line['requested_memory']) == -1 and int(_line['used_memory']) == -1:
                continue   
            qtime = default_sorted_attribute(line, 'submit_time')
            queued_times.add(qtime)
            f.write(line)
    return queued_times.get_list()  
    
def cmp_to_key(mycmp):
    'Convert a cmp= function into a key= function'
    class k(object):
        def __init__(self, obj, *args):
            self.obj = obj
        def __lt__(self, other):
            return mycmp(self.obj, other.obj) < 0
        def __gt__(self, other):
            return mycmp(self.obj, other.obj) > 0
        def __eq__(self, other):
            return mycmp(self.obj, other.obj) == 0
        def __le__(self, other):
            return mycmp(self.obj, other.obj) <= 0  
        def __ge__(self, other):
            return mycmp(self.obj, other.obj) >= 0
        def __ne__(self, other):
            return mycmp(self.obj, other.obj) != 0
    return k    

def from_isodatetime_2_timestamp(timestamp):
        p = re.compile(r'(\d{4})-(\d{2})-(\d{2})\s(\d{2}):(\d{2}):(\d{2})')
        m = p.search(timestamp).groups()
        # year, month, day, hour, minute, second, microsecond
        t = datetime(year=int(m[0]), month=int(m[1]), day=int(m[2]), hour=int(m[3]), minute=int(m[4]), second=int(m[5]))
        return int(t.timestamp())

def sorted_attr(line, reg_exp=(r'\d+\.\w+;.+;\w+@\w+\.eurora\.cineca\.it;\w+;(?P<queue_time>\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})__'), group_name='queue_time'):
    p = re.compile(reg_exp)
    return p.match(line).groupdict()[group_name]

def sort_job_function(x, y):
    return from_isodatetime_2_timestamp(sorted_attr(x)) - from_isodatetime_2_timestamp(sorted_attr(y))      

class time_demon:
    def __init__(self, interval, function, *args, **kwargs):
        self._timer = None
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self._timer = Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False
        
class watcher_demon:

    MAX_LENGTH = 2048
    PRINT_INTERVAL = 300
    
    def __init__(self, port):
        self.server_address = ('', port)
        af = socket.AF_INET
        self.sock = socket.socket(af, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(1)
        self.thread = None
        self.timedemon = None
        self.hastofinish = False
        self.const = CONSTANT()


    def start(self):
        self.thread = threading.Thread(target=self.listenForRequests)
        self.hastofinish = False
        self.timedemon = time_demon(self.PRINT_INTERVAL, self.resourceusageprint)
        self.thread.start()
        self.timedemon.start()

    def listenForRequests(self):
        # Listen for incoming connections
        # Reusing
        self.sock.bind(self.server_address)
        self.sock.listen(5)

        while not self.hastofinish:
            try:
                connection, client_address = self.sock.accept()
                with connection:
                    # print('connection from %s' % (client_address[0]))
                    data = json.loads(connection.recv(self.MAX_LENGTH).decode())
                    if isinstance(data, str):
                        response = {}
                        if data == 'localprogress':
                            response['input_filepath'] = self.const.input_filepath
                            response['progress'] = os.path.getsize(self.const.output_filepath) / os.path.getsize(self.const.input_filepath)
                            response['time'] = time.clock() - self.const.start_time
                        elif data == 'usage':
                            rm = self.const.resource_manager_instance
                            if rm is not None and rm.resources is not None:
                                response['usage'] = rm.resources.usage()
                            else:
                                response['usage'] = ''
                        elif data == 'globalprogress':
                            response['number_testfile_now'] = self.const.number_testfile_now
                            response['number_testfiles'] = self.const.number_testfiles
                            response['number_testrun_now'] = self.const.number_testrun_now
                            response['number_testruns'] = self.const.number_testruns
                            response['input_filepath'] = self.const.input_filepath
                        connection.sendall(json.dumps(response).encode())
                    connection.close()
            except socket.timeout:
                pass
        self.sock.close()

    def stop(self):
        self.hastofinish = True
        self.timedemon.stop()

    def resourceusageprint(self):
        rm = self.const.resource_manager_instance
        if rm is not None and rm.resources is not None:
            print('- ' + rm.resources.usage())


def generate_config(config_fp, **kwargs):
    _local = {}
    for k, v in kwargs.items():
        print(k, v)
        _local[k] = v
    with open(config_fp, 'w') as c:
        json.dump(_local, c, indent=2)

def hinted_tuple_hook(obj):
    if '__tuple__' in obj:
        return tuple(obj['items'])
    else:
        return obj

def load_config(config_fp):
    _dict = None
    with open(config_fp) as c:
        _dict = json.load(c, object_hook=hinted_tuple_hook)
    return _dict

def simulate_event(min_time, max_time):
    time.sleep(random.randint(min_time, max_time))
    
class Singleton(object):
    _instances = {}

    def __new__(class_, *args, **kwargs):
        if class_ not in class_._instances:
            class_._instances[class_] = super(Singleton, class_).__new__(class_, *args, **kwargs)
        return class_._instances[class_]

class CONSTANT(Singleton):
    """
        This class allows to load all config into the Singleton Object called CONSTANT. 
        For accessing to all the parameters, it will be possible only calling the parameters as its attribute.
    
        I.e:
        Config:
        PATH = '/path/to/'
        
        Program
        c = CONSTANT()
        print(c.PATH)
        
        >> /path/to/
    
        It's loaded into all base class by default!
        New attrs could be passed as dict (load_constants) or simply with (attr, value) (load_constant)
    """    
    def load_constants(self, _dict):
        for k, v in _dict.items():
            self.load_constant(k, v)
            
    def load_constant(self, k, v):
        setattr(self, k, v)

    #===========================================================================
    # An idea for improving the config is use the class name of parameters, ths could be controlled with the following method, but how??  
    # def __getattribute__(self, *args, **kwargs):
    #     return object.__getattribute__(self, *args, **kwargs)
    #===========================================================================


class str_:
    def __init__(self, text):
        self.text = text
    
    def __str__(self):
        return self.text


class str_datetime:
    
    def __init__(self, epoch_time):
        self.str_datetime = datetime.fromtimestamp(int(epoch_time)).strftime('%Y-%m-%d %H:%M:%S')
        
    def __format__(self, *args):
        return self.str_datetime
    
    def __str__(self):
        return self.str_datetime


class str_time:
    
    def __init__(self, secs):
        self.str_time = time.gmtime(int(secs))  # time.strftime('%H:%M:%S', time.gmtime(int(secs)))
        
    def __str__(self):
        return self.str_time
    
class str_resources:
    
    def __init__(self, nodes, resources):
        self.nodes = nodes
        self.resources = resources  # namedtuple('resources', [k for k in resources.keys()])(**resources)
        self.constants = CONSTANT()
        if hasattr(self.constants, 'resource_order'):
            self.order = getattr(self.constants, 'resource_order')
        else:
            self.order = list (self.resources.keys())
        
    def __str__(self):
        #=======================================================================
        # r = self.resources
        # print(self.nodes, r)
        # return '#'.join([';'.join([node.split('_')[1], str(r.core), str(r.gpu), str(r.mic), str(r.mem)]) for node in self.nodes]) + '#'
        #=======================================================================
        return '#'.join([';'.join([node.split('_')[1]] + [str(self.resources[_k]) for _k in self.order]) for node in self.nodes]) + '#'

class str_nodes:
    
    def __init__(self, nodes):
        self.nodes = nodes
    
    def __format__(self, format_spec):
        return self.__str__()
    
    def __str__(self):
        return ','.join([node.split('_')[1] for node in self.nodes])



class sorted_object_list():
    def __init__(self, sorting_priority, class_obj=None, _list=[]):
        assert(isinstance(sorting_priority, dict) and set(['main', 'break_tie']) <= set(sorting_priority.keys()))

        self.main_sort = sorting_priority['main']
        self.break_tie_sort = sorting_priority['break_tie']
        self.list = []
        self.main = []
        self.secondary = []
        self.map = {
            'pos': {},
            'id': {}
        }
        self.objects = {}
        # dict values, function or inner attributes of wrappred objs
        self._iter_func = lambda act, next: act.get(next) if isinstance(act, dict) else (getattr(act, next)() if callable(getattr(act, next)) else getattr(act, next))

        if _list:
            self.add(*_list)
            
    # @abstractmethod
    def add(self, *args):
        for arg in args:
            _id = getattr(arg, 'id')
            if _id in self.map['id']:
                continue
            self.objects[_id] = arg
            _main = reduce(self._iter_func, self.main_sort.split('.'), arg)  # getattr(arg, self.main_sort)
            _sec = reduce(self._iter_func, self.break_tie_sort.split('.'), arg)
            _pos = bisect_left(self.main, _main)
            main_pos_r = bisect_right(self.main, _main)
            if _pos == main_pos_r:
                self.list.insert(_pos, _id)
                self.main.insert(_pos, _main)
                self.secondary.insert(_pos, _sec)
            else:
                _pos = bisect_left(self.secondary[_pos :main_pos_r], _sec) + _pos
                self.list.insert(_pos, _id)
                self.main.insert(_pos, _main)
                self.secondary.insert(_pos, _sec)
            self.map_insert(self.map['id'], self.map['pos'], _pos, _id)
    
    def _get_value(self, arg, attr):
        
        if isinstance(self.break_tie_sort, tuple):
            _sec = arg
            for _attr in self.break_tie_sort:
                _sec = getattr(_sec, _attr)
        else:
            _sec = getattr(arg, self.break_tie_sort)
    
    def map_insert(self, ids_, poss_, new_pos, new_id):
        n_items = len(ids_)
        if n_items > 0:
            if not(new_pos in poss_):
                poss_[new_pos] = new_id
                ids_[new_id] = new_pos
            else:
                self.make_map(ids_, poss_, new_pos)
        else:
            ids_[new_id] = new_pos
            poss_[new_pos] = new_id
    
    # Improve this
    def make_map(self, ids_, poss_, new_pos=0, debug=False):    
        for _idx, _id in enumerate(self.list[new_pos:]):
            ids_[_id] = _idx + new_pos
            poss_[_idx + new_pos] = _id
        if len(ids_) == len(poss_):
            return
        for p in list(poss_.keys()):
            if p > _idx:
                del poss_[p] 
        
    def remove(self, *args, **kwargs):
        for id in args:
            assert(id in self.objects)
            del self.objects[id]            
            self._remove(self.map['id'][id], **kwargs)
            print(self.map)
            
    def _remove(self, _pos, **kwargs):
        del self.list[_pos]
        del self.secondary[_pos]
        del self.main[_pos]
        
        _id = self.map['pos'].pop(_pos)
        del self.map['id'][_id]
        self.make_map(self.map['id'], self.map['pos'], **kwargs)

                
    def get(self, pos):
        return self.list[pos]

    def get_object(self, id):
        return self.objects[id]
     
    def get_list(self):
        return self.list
    
    def get_object_list(self):
        return [self.objects[_id] for _id in self.list] 
                
    def __len__(self):
        return len(self.list)
    
    # Return None if there is no coincidence
    def pop(self, id=None, pos=None):
        assert(not all([id, pos])), 'Pop only accepts one or zero arguments'
        if not self.list:
            return None
        elif id:
            return self._specific_pop_id(id)
        elif pos:
            return self._specific_pop_pos(pos)
        else:
            _id = self.list[0]
            self._remove(0)
            return self.objects.pop(_id)        
    
    def _specific_pop_id(self, id):
        _obj = self.objects.pop(id, None)
        if _obj:
            self._remove(self.map['id'][id])
        return _obj
    
    def _specific_pop_pos(self, pos):
        _id = self.map['pos'].pop(pos, None)
        if _id:
            self.map['pos'][pos] = _id
            self._remove(pos)
        return self.objects.pop(_id, None)        

    def __iter__(self):
        self.actual_index = 0
        return self

    def __next__(self):
        try:
            self.actual_index += 1
            return self.list[self.actual_index - 1]
        except IndexError:
            raise StopIteration
    
    def get_reversed_list(self):
        return list(reversed(self.list))
    
    def get_reversed_object_list(self):
        return [ self.objects[_id] for _id in reversed(self.list)]
    
    def __str__(self):
        return str(self.list)
    
class sorted_list:
    def __init__(self, _list=[]):
        assert(isinstance(_list, (list)))
        self.list = []
        if _list:
            self.add(*_list)
    
    def add(self, *args):
        for arg in args:
            if len(self.list) == 0:
                self.list.append(arg)
            else:
                _num = arg
                pos = bisect(self.list, _num)
                #===============================================================
                # mid = int(len(self.list) // 2)
                # if self.list[mid] > _num:
                #     pos = bisect(self.list, _num, hi=mid)
                # else:
                #     pos = bisect(self.list, _num, hi=mid)
                #===============================================================
                if self.list[pos - 1] != _num:
                    self.list.insert(pos, _num)
                    
    def get_list(self):
        return self.list
   
    def find(self, _num):
        return bisect(self.list, _num) - 1
    
    def remove(self, *args):
        for arg in args:
            self.list.remove(arg)
                
    def get(self, pos):
        return self.list[pos]
                
    def __len__(self):
        return len(self.list)
    
    def pop(self):
        if self.list:
            return self.list.pop(0)
        return None

    def __iter__(self):
        self.actual_index = 0
        return self

    def __next__(self):
        try:
            self.actual_index += 1
            return self.list[self.actual_index - 1]
        except IndexError:
            raise StopIteration
    
    def __str__(self):
        return str(self.list)
    
    def _check_sort(self):
        
        for i in range(len(self.list) - 1):
            if self.list[i] >= self.list[i + 1]:
                self.list[0:i + 1]
                raise Exception('Sorting problem!')
            
class FrozenDict(Mapping):
    """
        Inmutable dictionary useful for storing parameter that are dinamycally loaded
    """
    def __init__(self, *args, **kwargs):
        self._d = dict(*args, **kwargs)
        self._hash = None

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)

    def __getitem__(self, key):
        return self._d[key]

    def __hash__(self):
        if self._hash is None:
            self._hash = 0
            for pair in self.iteritems():
                self._hash ^= hash(pair)
        return self._hash
    
def clean_results(*args):
    for fp in args:
        if os.path.isfile(fp) and os.path.exists(fp):
            os.remove(fp)
            
if __name__ == '__main__2':
    Resource = namedtuple('Resource', ['q', 'w'])
    Job = namedtuple('Job', ['id', 'resources', 'vars'])
    lista = [
        Job(**{'id': 'job.1', 'resources': Resource(**{'q': '5', 'w':'2'}), 'vars': {'w': 2} }),
        Job(**{'id': 'job.2', 'resources': Resource(**{'q': '5', 'w':'1'}), 'vars': {'w': 1} }),
        Job(**{'id': 'job.3', 'resources': Resource(**{'q': '3', 'w':'1'}), 'vars': {'w': 1} }),
        Job(**{'id': 'job.4', 'resources': Resource(**{'q': '1', 'w':'10'}), 'vars': {'w': 10} }),
        Job(**{'id': 'job.5', 'resources': Resource(**{'q': '1', 'w':'1'}), 'vars': {'w': 1} }),
        Job(**{'id': 'job.6', 'resources': Resource(**{'q': '6', 'w':'1'}), 'vars': {'w': 1} }),
        Job(**{'id': 'job.7', 'resources': Resource(**{'q': '6', 'w':'7'}), 'vars': {'w': 7} }),
        Job(**{'id': 'job.8', 'resources': Resource(**{'q': '4', 'w':'2'}), 'vars': {'w': 2} }),
        Job(**{'id': 'job.9', 'resources': Resource(**{'q': '4', 'w':'1'}), 'vars': {'w': 1} }),
        ]
    sorting_priority = {'main': 'resources.q', 'break_tie': 'vars.w'}
    s_obj = Job
    slist = sorted_object_list(sorting_priority, s_obj)
    slist.add(*lista)
    print('All elements: ', slist)
    print('Inverse List: ', slist.get_reversed_list())
    _pop = slist.pop()
    print('Pop : ', _pop, '. Remaining list: ', slist)
    _pop = slist.pop(pos=1)
    print('Pop : ', _pop, '. Remaining list: ', slist)
    _pop = slist.pop(id='job.2')
    print('Pop : ', _pop, '. Remaining list: ', slist)
    _id = 'job.1'
    slist.remove(_id, debug=True)
    print('Removing : ', _id, '. Remaining list: ', slist)
    while slist.pop():
        print(slist)
            
if __name__ == '__main__2':
    Job = namedtuple('Job', ['id', 'q', 'w'])
    lista = [
        Job(**{'id': 'job.1', 'q': '5', 'w':'2'}),
        Job(**{'id': 'job.2', 'q': '5', 'w':'1'}),
        Job(**{'id': 'job.3', 'q': '3', 'w':'1'}),
        Job(**{'id': 'job.4', 'q': '1', 'w':'10'}),
        Job(**{'id': 'job.5', 'q': '1', 'w':'1'}),
        Job(**{'id': 'job.6', 'q': '6', 'w':'1'}),
        Job(**{'id': 'job.7', 'q': '6', 'w':'7'}),
        Job(**{'id': 'job.8', 'q': '4', 'w':'2'}),
        Job(**{'id': 'job.9', 'q': '4', 'w':'1'}),
        ]
    sorting_priority = {'main': 'q', 'break_tie':'w'}
    s_obj = Job
    slist = sorted_object_list(sorting_priority, s_obj)
    slist.add(*lista)
    print(slist)
    print(slist.reverse())
    if 'job.8' in slist:
        print('si')
    slist.remove(*['job.8'])
    print(slist)
    if 'job.8' not in slist:
        print('no')
    
if __name__ == '__main__':
    random.seed(0)
    lista = sorted_list([])
    
    max_val = 10000
    values = random.sample(range(1, max_val * 2), max_val)
    random.shuffle(values)
    print('Adding new elements and resorting everytime')
    i_time = time.clock()
    for _v in values:
        lista.add(_v)
    print('Custom sorting time: ', time.clock() - i_time, len(lista.get_list()))
    
    i_time = time.clock()
    inc_list = []
    for i in values:
        inc_list.append(i)
        sorted(inc_list)
    print('Sorting time: ', time.clock() - i_time, len(values))
    
    print('Full list sorting')
    lista = sorted_list([])
    i_time = time.clock()
    lista.add(*values)
    print('Custom sorting time: ', time.clock() - i_time, len(lista.get_list()))
    
    i_time = time.clock()
    sorted(values)
    print('Sorting time: ', time.clock() - i_time, len(values))