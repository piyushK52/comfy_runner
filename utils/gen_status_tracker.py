import os
import time
import fcntl


class GenerationStatusTracker:
    def __init__(self, file_name="generation_status.txt"):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.file_path = os.path.join(current_dir, file_name)
        self.cache = {}
        self.last_file_check = 0
        self.file_check_interval = 1  # check file every 1 second

    def mark_generation_cancelled(self, client_id):
        if not client_id:
            return False

        with open(self.file_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(f"{client_id},True,{time.time()}\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        self.cache[client_id] = (True, time.time())
        return True

    def is_generation_cancelled(self, client_id):
        if not client_id:
            return False

        current_time = time.time()
        if current_time - self.last_file_check > self.file_check_interval:
            self._update_cache_from_file()
            self.last_file_check = current_time

        status, _ = self.cache.get(client_id, (False, 0))
        return status

    def _update_cache_from_file(self):
        if not os.path.exists(self.file_path):
            return

        with open(self.file_path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                for line in f:
                    client_id, status, timestamp = line.strip().split(",")
                    status = status.lower() == "true"
                    timestamp = float(timestamp)
                    if (
                        client_id not in self.cache
                        or timestamp > self.cache[client_id][1]
                    ):
                        self.cache[client_id] = (status, timestamp)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
