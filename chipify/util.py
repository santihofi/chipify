import yaml
import os

class Stimuli:
    def __init__(self, yaml_file=None):
        self.params = {}
        self.tests = []
        if yaml_file:
            self._load_from_yaml(yaml_file)
            
    def _load_from_yaml(self, file_path):
        with open(file_path, 'r') as file:
            data = yaml.safe_load(file)
            
        # 1. Parameter 1:1 übernehmen
        self.params = data.get('parameters', {})
        
        for key, value in self.params.items():
            if isinstance(value, str) and value.startswith("range("):
                # Extrahiert die Zahl aus den Klammern und konvertiert sie
                num = int(value.replace("range(", "").replace(")", ""))
                self.params[key] = list(range(num))
        
        # 2. Tests generieren
        for tb_path, measurements in data.get('tests', {}).items():
            transient_signals = []
            measure: dict = {}
            value_lst = []
            for val_name, bounds in measurements.items():
                if val_name == 'transient_signals':
                    # bounds is a list of signal names, e.g. ["v(out)", "v(in)"]
                    if isinstance(bounds, list):
                        transient_signals = [str(s) for s in bounds]
                    continue
                if val_name == 'measure':
                    # VACASK measure expressions: {value_name: "expression_string"}
                    if isinstance(bounds, dict):
                        measure = {k: str(v) for k, v in bounds.items()}
                    continue
                value_lst.append(
                    Value(
                        name=val_name,
                        vmin=bounds.get('min'),
                        vmax=bounds.get('max'),
                        vtyp=bounds.get('typ')
                    )
                )
            t = Test(tb_path, value_lst)
            t.transient_signals = transient_signals
            t.measure = measure
            self.addTest(t)

    def addTest(self, test):
        self.tests.append(test)

class Test:
    def __init__(self, tb_path, value_lst):
        self.tb_path = tb_path
        self.value_lst = value_lst
        self.template = ""
        self.transient_signals: list = []  # populated by Stimuli._load_from_yaml
        self.measure: dict = {}            # VACASK measure expressions {name: expr_str}
        
class Value:
    def __init__(self, name, vmin, vmax, vtyp):
        self.name = name
        self.vmin = vmin
        self.vmax = vmax
        self.vtyp = vtyp
        
    def isPass(self, val):
        if self.vmin is not None and val < self.vmin:
            return False
        if self.vmax is not None and val > self.vmax:
            return False
        return True
    
def get_num_cores():
    try:
        available_cores = len(os.sched_getaffinity(0))
    except AttributeError:
        available_cores = os.cpu_count()
        
    return max(1, available_cores - 1)