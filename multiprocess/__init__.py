from collections import namedtuple
from contextlib import contextmanager
from multiprocessing import Manager, Queue, Process
from multiprocessing.managers import ListProxy

from multiprocess.progress_bar import progress_bar
from multiprocess.signals import STOP
from utils import tqdm
from utils import available_cores


def worker(func, input: Queue, progress_bar_updates: Queue, output: ListProxy, *args):
    """Generic worker for map-like operations with progress bar.

    Calls `func` on every object provided on `input_` queue
    until `STOP` (None) is received. After each step queues
    an update on `progress_bar` queue.
    Results of `func` calls are appended to `output` list.
    
    Args:
        func: function to be called on queued objects
        input: input queue
        progress_bar_updates: progress_bar queue
        output: managed list for results
        *args: additional positional arguments to be passed to `func`
    """
    while True:
        data = input.get()

        if data is STOP:
            return

        result = func(data, *args)

        output.append(result)
        progress_bar_updates.put(1)


api_template = namedtuple('API', 'queue, results')


@contextmanager
def multiprocessing_queue(target, args, processes, total):
    manager = Manager()
    results = manager.list()
    queue = Queue()

    api = api_template(queue, results)

    processes_cnt = processes or available_cores()

    # do not start more processes than necessary
    if processes_cnt > total:
        processes_cnt = total

    with progress_bar(total) as progress_queue:

        worker_args = [target, queue, progress_queue, results]

        if args:
            worker_args.extend(args)

        processes = [
            Process(target=worker, args=worker_args)
            for _ in range(processes_cnt)
        ]

        yield api

        for _ in processes:
            queue.put(STOP)

        for process in processes:
            process.start()

        for process in processes:
            process.join()


# TODO: is it possible to use partial instead of shared_args?
class Pool:
    """A pool with support for shared arguments and progress bar.

    Interface is partially compatible with `multiprocessing.Pool`.

    Only imap method is implemented so far.
    """

    def __init__(self, processes):
        self.processes = processes

    def imap(self, func, iterable, shared_args=tuple()):
        """Iteratively apply function to items ofo `iterable` and return results.

        The order of resultant list is not guaranteed to be preserved.
        Items will be passed from `iterable` to pool queue one by one.

        Args:
            func: function to be applied to items
            iterable: an iterable with items
            shared_args: positional arguments to be passed to func after item
        """

        if self.processes == 1:
            # for profiling and debugging a single process works better
            # (and there is less overhead than forking for one more)
            return map(lambda i: func(i, *shared_args), tqdm(iterable))

        with multiprocessing_queue(func, shared_args, self.processes, total=len(iterable)) as api:
            for item in iterable:
                api.queue.put(item)

        return api.results