import os
import time
import threading
import portalocker


class GenerationStatusTracker:
    def __init__(self, file_name="generation_status.txt", lock_timeout=10):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.file_path = os.path.join(current_dir, file_name)
        self.cache = {}
        self.last_file_check = 0
        self.file_check_interval = 1  # check file every 1 second
        self.lock = threading.Lock()
        self.lock_timeout = lock_timeout  # timeout for acquiring lock in seconds

    def mark_generation_cancelled(self, client_id):
        if not client_id:
            return False

        try:
            with portalocker.Lock(self.file_path, "a", timeout=self.lock_timeout) as f:
                f.write(f"{client_id},True,{time.time()}\n")
                f.flush()
                os.fsync(f.fileno())
        except portalocker.exceptions.LockException:
            print(
                f"Failed to acquire lock for writing within {self.lock_timeout} seconds."
            )
            return False

        with self.lock:
            self.cache[client_id] = (True, time.time())
        return True

    def is_generation_cancelled(self, client_id):
        if not client_id:
            return False

        current_time = time.time()
        if current_time - self.last_file_check > self.file_check_interval:
            self._update_cache_from_file()
            self.last_file_check = current_time

        with self.lock:
            status, _ = self.cache.get(client_id, (False, 0))
        return status

    def _update_cache_from_file(self):
        if not os.path.exists(self.file_path):
            return

        try:
            with portalocker.Lock(self.file_path, "r", timeout=self.lock_timeout) as f:
                for line in f:
                    client_id, status, timestamp = line.strip().split(",")
                    status = status.lower() == "true"
                    timestamp = float(timestamp)
                    with self.lock:
                        if (
                            client_id not in self.cache
                            or timestamp > self.cache[client_id][1]
                        ):
                            self.cache[client_id] = (status, timestamp)
        except portalocker.exceptions.LockException:
            print(
                f"Failed to acquire lock for reading within {self.lock_timeout} seconds."
            )


# quick check to test cross-platform compatibility
if __name__ == "__main__":
    tracker = GenerationStatusTracker()
    tracker.mark_generation_cancelled("client1")
    print(tracker.is_generation_cancelled("client1"))
    print(tracker.is_generation_cancelled("client2"))
