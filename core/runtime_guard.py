"""Cross-game observation/action guard. It does not infer game achievements."""
import time


class RuntimeViolation(RuntimeError):
    pass


class RuntimeGuard:
    def __init__(self, task, max_repeats=6, max_age=5.0, clock=None, on_failure=None):
        self.task = task
        self.max_repeats, self.max_age = max_repeats, max_age
        self.clock = clock or time.monotonic
        self.on_failure = on_failure
        self.failed = None
        self.frame = None
        self.observed_at = None
        self.sample = None
        self.actions = {}

    def fail(self, reason):
        if self.failed is None:
            self.failed = str(reason)
            if self.on_failure:
                try:
                    self.on_failure(self.failed, self.frame)
                except Exception:
                    pass  # Evidence I/O must never reopen input or mask the violation.
        raise RuntimeViolation(self.failed)

    def check(self):
        if self.failed is not None:
            raise RuntimeViolation(self.failed)

    def observe(self, frame):
        self.check()
        if frame is None or not hasattr(frame, 'shape') or len(frame.shape) < 2 or frame.size == 0:
            self.fail('截图无效，停止输入')
        import numpy as np
        h, w = frame.shape[:2]
        sample = np.asarray(frame)[::max(1, h // 36), ::max(1, w // 64)].astype('float32')
        if self.sample is None or sample.shape != self.sample.shape or np.mean(np.abs(sample - self.sample)) > 8:
            self.actions.clear()
            self.sample = sample
        self.frame = frame
        self.observed_at = self.clock()

    def before_action(self, target):
        self.check()
        if self.observed_at is None or self.clock() - self.observed_at > self.max_age:
            self.fail('缺少近期有效截图，禁止按旧画面继续操作')
        key = str(target)
        count = self.actions.get(key, 0) + 1
        if count > self.max_repeats:
            self.fail('画面无明确进展且重复操作过多: ' + key)
        self.actions[key] = count

    def finish(self, native_success, verified=True):
        self.check()
        if native_success is not True or verified is not True:
            self.fail('任务返回或结束状态未确认，不报告成功')
        return True
