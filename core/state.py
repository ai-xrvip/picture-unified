"""统一状态管理：每个数据源一个 JSON seen 文件 + 可选页码文件，带跨平台文件锁。"""
import json
import os

try:
    import fcntl  # POSIX
except ImportError:
    fcntl = None
try:
    import msvcrt  # Windows
except ImportError:
    msvcrt = None


class StateFile:
    """按数据源隔离的 seen 集合，JSON 数组格式，带文件锁防止并发写。"""

    def __init__(self, path):
        self.path = path

    def load(self):
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            return set()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(data)
            if isinstance(data, dict):
                return set(data.keys())
        except Exception as e:
            print(f"  ⚠️ 状态文件解析失败 {self.path}: {e}")
        return set()

    def save(self, seen):
        self._locked_save(sorted(seen))

    def _locked_save(self, data):
        lock_path = self.path + ".lock"
        lock_fd = self._acquire_lock(lock_path)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        finally:
            self._release_lock(lock_fd, lock_path)

    @staticmethod
    def _acquire_lock(lock_path):
        fd = None
        try:
            fd = open(lock_path, "w")
            fd.write(" ")
            fd.flush()
            fd.seek(0)
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt:
                msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
            return fd
        except (OSError, IOError):
            print("  ⚠️ 另一个实例正在运行，本次跳过写状态")
            try:
                if fd is not None:
                    fd.close()
            except Exception:
                pass
            return None

    @staticmethod
    def _release_lock(fd, lock_path):
        if fd is None:
            return
        try:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_UN)
            elif msvcrt:
                fd.seek(0)
                msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        try:
            fd.close()
        except Exception:
            pass
        try:
            os.remove(lock_path)
        except OSError:
            pass


def load_page(path, default):
    if not os.path.exists(path):
        return default
    try:
        return max(int(open(path).read().strip()), 1)
    except Exception:
        return default


def save_page(path, page):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(str(page))
