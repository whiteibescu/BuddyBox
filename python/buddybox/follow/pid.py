class PID:
    def __init__(self, kp=0.0, ki=0.0, kd=0.0, out_limit=1.0, i_limit=None, d_filter=0.5):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_limit = out_limit
        self.i_limit = i_limit if i_limit is not None else out_limit
        self.d_filter = d_filter
        self.reset()

    def reset(self):
        self._integral = 0.0
        self._prev_error = None
        self._prev_t = None
        self._d_term = 0.0
        self.last_output = 0.0

    def update(self, error, now):
        dt = 0.0 if self._prev_t is None else max(0.0, now - self._prev_t)
        p = self.kp * error
        if dt > 0.0:
            self._integral += error * dt
            lim = self.i_limit / self.ki if self.ki else 0.0
            self._integral = max(-lim, min(lim, self._integral)) if self.ki else 0.0
            raw_d = (error - self._prev_error) / dt if self._prev_error is not None else 0.0
            self._d_term += (raw_d - self._d_term) * self.d_filter
        i = self.ki * self._integral
        d = self.kd * self._d_term
        out = max(-self.out_limit, min(self.out_limit, p + i + d))
        self._prev_error = error
        self._prev_t = now
        self.last_output = out
        return out
