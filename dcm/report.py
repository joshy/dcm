import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import (Optional, Dict, List, Any, Union, TypeVar, Generic, Iterator, ItemsView, 
                    KeysView, ValuesView)

import rich.progress


log = logging.getLogger(__name__)


@dataclass
class ProgressTaskBase:
    description: str

    total: Optional[int]

    start_time: datetime

    min_seconds: float

    show_indeterminate: bool


T = TypeVar('T', bound=ProgressTaskBase)


class ProgressHookBase(Generic[T]):
    '''Base class for hooking in to progress updates from a report'''

    def_min_seconds: float = 3.0

    def_show_indeterminate: bool = False

    def create_task(self, description: str, total: Optional[int] = None, **kwargs : Any) -> T:
        raise NotImplementedError

    def set_total(self, task: T, total: int) -> None:
        raise NotImplementedError

    def advance(self, task: T, amount: float = 1.0) -> None:
        raise NotImplementedError

    def end(self, task: T) -> None:
        raise NotImplementedError


@dataclass
class RichProgressTask(ProgressTaskBase):

    _task: Optional[rich.progress.TaskID] = field(default=None, init=False, repr=False)

    _task_opts: Dict[str, Any] = field(default_factory=dict, init=False, repr=False)


class RichProgressHook(ProgressHookBase[RichProgressTask]):
    '''Hook for console progress bar provided by `rich` package'''

    def __init__(self, progress: rich.progress.Progress):
        self._progress = progress

    def create_task(self, description: str, total: Optional[int] = None, **kwargs: Any) -> RichProgressTask:
        if 'min_seconds' not in kwargs:
            kwargs['min_seconds'] = self.def_min_seconds
        if 'show_indeterminate' not in kwargs:
            kwargs['show_indeterminate'] = self.def_show_indeterminate
        res = RichProgressTask(description, total, datetime.now(), **kwargs)
        self._update_task(res)
        return res

    def set_total(self, task: RichProgressTask, total: int) -> None:
        task.total = total
        self._update_task(task)
    
    def advance(self, task: RichProgressTask, amount: float = 1.0) -> None:
        self._update_task(task, advance=amount)

    def end(self, task: RichProgressTask) -> None:
        if task._task is not None:
            self._progress.stop_task(task._task)
            task._task = None
        
    def _update_task(self, task: RichProgressTask, advance: Optional[float] = None) -> None:
        if task.total is None:
            if not task.show_indeterminate:
                return
            task._task_opts['start'] = False
        else:
            task._task_opts['total'] = task.total
        if task._task_opts.get('visible', False) == False:
            if (task.min_seconds <= 0.0 or 
                (datetime.now() - task.start_time).total_seconds() > task.min_seconds
                ):
                task._task_opts['visible'] = True
        if task._task is None:
            task._task = self._progress.add_task(task.description, **task._task_opts)
            if advance is not None:
                self._progress.advance(task._task, advance)
        else:
            self._progress.update(task._task, advance=advance, **task._task_opts)


class Report:
    '''Abstract base class for all reports'''

    def __init__(self, 
                 description: Optional[str] = None, 
                 n_expected: Optional[int] = None,
                 prog_hook: Optional[ProgressHookBase[Any]] = None
                 ):
        self._description = description
        self._n_expected = n_expected
        self._n_input = 0
        self._done = False
        self._task = None
        self._prog_hook: Optional[ProgressHookBase[Any]] = None
        self.set_prog_hook(prog_hook)

    @property
    def description(self) -> str:
        if self._description is None:
            self._description = self._auto_descr()
        return self._description
    
    @description.setter
    def description(self, val: str) -> None:
        self._description = val

    @property
    def n_expected(self) -> Optional[int]:
        '''Number of expected inputs, or None if unknown'''
        return self._n_expected

    @n_expected.setter
    def n_expected(self, val: int) -> None:
        self._n_expected = val
        if self._prog_hook is not None:
            if self._task is None:
                self._init_task()
            self._prog_hook.set_total(self._task, val)

    @property
    def n_input(self) -> int:
        '''Number of inputs seen so far'''
        return self._n_input

    @property
    def done(self) -> bool:
        return self._done

    @done.setter
    def done(self, val: bool) -> None:
        self._set_done(val)

    def _init_task(self) -> None:
        assert self._prog_hook is not None
        self._task = self._prog_hook.create_task(self.description, total=self._n_expected)

    def set_prog_hook(self, prog_hook: Optional[ProgressHookBase[Any]]) -> None:
        if self._prog_hook is not None:
            assert prog_hook == self._prog_hook
            return
        if prog_hook is None:
            return
        self._prog_hook = prog_hook
        if self._description is not None:
            self._init_task()
    
    def count_input(self) -> None:
        self._n_input += 1
        if self._prog_hook is not None:
            if self._task is None:
                self._init_task()
            self._prog_hook.advance(self._task)

    @property
    def n_success(self) -> int:
        '''Number of successfully handled inputs'''
        raise NotImplementedError

    @property
    def n_errors(self) -> int:
        '''Number of errors, where a single input can cause multiple errors'''
        raise NotImplementedError

    @property
    def n_warnings(self) -> int:
        '''Number of warnings, where a single input can cause multiple warnings
        '''
        raise NotImplementedError

    @property
    def all_success(self) -> bool:
        return self.n_errors + self.n_warnings == 0

    def __len__(self) -> int:
        return self.n_success + self.n_warnings + self.n_errors

    def log_issues(self) -> None:
        '''Log a summary of error/warning statuses'''
        raise NotImplementedError

    def check_errors(self) -> None:
        '''Raise an exception if any errors occured'''
        raise NotImplementedError

    # TODO: This is tricky to support for some subclasses, separate it out?
    def clear(self) -> None:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self._description}, n_expected={self._n_expected}, n_input={self._n_input})'

    def __str__(self) -> str:
        lines = [f'{self.description}:']
        stat = 'COMPLETED' if self._done else 'PENDING'
        lines.append(f'  * status: {stat}')
        if self.n_success > 0:
            lines.append(f'  * n_success: {self.n_success}')
        if self.n_warnings > 0:
            lines.append(f'  * n_warnings {self.n_warnings}')
        if self.n_errors > 0:
            lines.append(f'  * n_errors {self.n_errors}')
        # TODO: Setup method for including warning/error details
        return '\n'.join(lines)
    
    def _auto_descr(self) -> str:
        res = self.__class__.__name__.lower()
        if res.endswith('report') and len(res) > len('report'):
            res = res[:-len('report')]
        return res
    
    def _set_done(self, val: bool) -> None:
        if not val:
            raise ValueError("Setting `done` to False is not allowed")
        if self._done:
            raise ValueError("Report was already marked done")
        self._done = True
        if self._prog_hook is not None and self._task is not None:
            self._prog_hook.end(self._task)


class MultiError(Exception):
    def __init__(self, errors: List[Exception]):
        self.errors = errors

    def __str__(self) -> str:
        res = ['Multiple Errors:'] + [str(e) for e in self.errors]
        return '\n\t'.join(res)


R = TypeVar('R', bound=Union[Report, 'MultiReport[Any]'])


class MultiReport(Report, Generic[R]):
    '''Abstract base class for all MultiReports'''

    def gen_reports(self) -> Iterator[R]:
        raise NotImplementedError

    @property
    def done(self) -> bool:
        return self._done

    @done.setter
    def done(self, val: bool) -> None:
        super()._set_done(val)
        if not all(r.done for r in self.gen_reports()):
            log.warning("Not all sub-reports were marked done before top-level report")
            # TODO: Raise here?

    @property
    def n_success(self) -> int:
        return sum(1 for r in self.gen_reports() if r.all_success)

    @property
    def n_warnings(self) -> int:
        return sum(1 for r in self.gen_reports() if r.n_warnings != 0)

    @property
    def n_errors(self) -> int:
        return sum(1 for r in self.gen_reports() if r.n_errors != 0)

    @property
    def n_sub_success(self) -> int:
        total = 0
        for r in self.gen_reports():
            if hasattr(r, 'n_sub_success'):
                total += r.n_sub_success
            else:
                total += r.n_success
        return total

    @property
    def n_sub_warnings(self) -> int:
        total = 0
        for r in self.gen_reports():
            if hasattr(r, 'n_sub_warnings'):
                total += r.n_sub_warnings
            else:
                total += r.n_warnings
        return total
    
    @property
    def n_sub_errors(self) -> int:
        total = 0
        for r in self.gen_reports():
            if hasattr(r, 'n_sub_errors'):
                total += r.n_sub_errors
            else:
                total += r.n_errors
        return total

    @property
    def all_success(self) -> bool:
        return self.n_errors + self.n_warnings == 0

    def log_issues(self) -> None:
        '''Produce log messages for any warning/error statuses'''
        for report in self.gen_reports():
            report.log_issues()

    def __str__(self) -> str:
        lines = [f'{self.description}:']
        stat = 'COMPLETED' if self._done else 'PENDING'
        lines.append(f'  * status: {stat}')
        if self.n_success > 0:
            lines.append(f'  * n_success: {self.n_success} ({self.n_sub_success} sub-ops)')
        if self.n_warnings > 0:
            lines.append(f'  * n_warnings {self.n_warnings} ({self.n_sub_warnings} sub-ops)')
        if self.n_errors > 0:
            lines.append(f'  * n_errors {self.n_errors} ({self.n_sub_errors} sub-ops)')
        if not self.all_success:
            lines.append('\n  Sub-Reports:')
            for rep in self.gen_reports():
                if rep.all_success:
                    continue
                rep_str = str(rep).replace('\n', '\n    ')
                lines.append(f'    * {rep_str}')
        return '\n'.join(lines)


class MultiListReport(MultiReport[R]):
    '''Sequence of related reports'''
    def __init__(self, 
                 description: Optional[str] = None, 
                 sub_reports: Optional[List[R]] = None,
                 prog_hook: Optional[ProgressHookBase[Any]] = None, 
                 n_expected: Optional[int] = None,
                 ):
        self._sub_reports = [] if sub_reports is None else sub_reports
        super().__init__(description, n_expected, prog_hook)

    def __getitem__(self, idx: int) -> R:
        return self._sub_reports[idx]

    def __len__(self) -> int:
        return len(self._sub_reports)

    def __iter__(self) -> Iterator[R]:
        for report in self._sub_reports:
            yield report

    def append(self, val: R) -> None:
        val.set_prog_hook(self._prog_hook)
        self._sub_reports.append(val)
        self.count_input()

    def gen_reports(self) -> Iterator[R]:
        for report in self._sub_reports:
            yield report

    def check_errors(self) -> None:
        '''Raise an exception if any errors have occured so far'''
        errors = []
        for sub_report in self._sub_reports:
            try:
                sub_report.check_errors()
            except Exception as e:
                errors.append(e)
        if errors:
            raise MultiError(errors)

    def clear(self) -> None:
        incomplete = []
        for sub_report in self._sub_reports:
            if not sub_report.done:
                incomplete.append(sub_report)
                sub_report.clear()
        self._n_input = len(incomplete)
        if self._n_expected is not None:
            self._n_expected -= len(self._sub_reports) - self._n_input
        self._sub_reports = incomplete


class MultiKeyedError(Exception):
    def __init__(self, errors: Dict[Any, Exception]):
        self.errors = errors

    def __str__(self) -> str:
        res = ['Multiple Errors:'] + [f'{k}: {e}' for k, e in self.errors.items()]
        return '\n\t'.join(res)


K = TypeVar('K')


class MultiDictReport(MultiReport[R], Generic[K, R]):
    '''Collection of related reports, each identified with a unique key'''
    def __init__(self, 
                 description: Optional[str] = None, 
                 sub_reports: Optional[Dict[K, R]] = None,
                 prog_hook: Optional[ProgressHookBase[Any]] = None, 
                 n_expected: Optional[int] = None,
                 ):
        self._sub_reports = {} if sub_reports is None else sub_reports
        super().__init__(description, n_expected, prog_hook)

    def __getitem__(self, key: K) -> R:
        return self._sub_reports[key]

    def __setitem__(self, key: K, val: R) -> None:
        if key in self._sub_reports:
            raise ValueError(f"Already have report with key: {key}")
        val.set_prog_hook(self._prog_hook)
        self._sub_reports[key] = val
        self.count_input()

    def __len__(self) -> int:
        return len(self._sub_reports)

    def __iter__(self) -> Iterator[K]:
        for key in self._sub_reports:
            yield key

    def __contains__(self, key: K) -> bool:
        return key in self._sub_reports

    def keys(self) -> KeysView[K]:
        return self._sub_reports.keys()

    def values(self) -> ValuesView[R]:
        return self._sub_reports.values()

    def items(self) -> ItemsView[K, R]:
        return self._sub_reports.items()

    def gen_reports(self) -> Iterator[R]:
        for report in self._sub_reports.values():
            yield report

    def check_errors(self) -> None:
        '''Raise an exception if any errors have occured so far'''
        errors = {}
        for key, sub_report in self._sub_reports.items():
            try:
                sub_report.check_errors()
            except Exception as e:
                errors[key] = e
        if errors:
            raise MultiKeyedError(errors)

    def clear(self) -> None:
        incomplete = {}
        for key, sub_report in self._sub_reports.items():
            if not sub_report.done:
                incomplete[key] = sub_report
                sub_report.clear()
        self._n_input = len(incomplete)
        if self._n_expected is not None:
            self._n_expected -= len(self._sub_reports) - self._n_input
        self._sub_reports = incomplete

    def __str__(self) -> str:
        lines = [f'{self.__class__.__name__}:']
        for key, rep in self._sub_reports.items():
            rep_str = str(rep).replace('\n', '\n\t')
            lines.append(f'\t{rep_str}')
        return '\n'.join(lines)
