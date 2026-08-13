"""数据源注册表。"""
REGISTRY = {}


def register(name, label, run):
    REGISTRY[name] = {"name": name, "label": label, "run": run}
    return run


def list_sources():
    return list(REGISTRY)
