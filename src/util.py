    
class Stimuli:
    def __init__(self):
        self.params = {}
        self.tests = []
    
    def addEnumParam(self, name, values):
        self.params[name] = values
        
    def addRangeParam(self, start, stop, step):
        self.params[name] = range(start, stop, step)
    
    def addTest(self, test):
        self.tests.append(test)
    
class Test:
    def __init__(self, tb_path, value_lst):
        self.tb_path = tb_path
        self.value_lst = value_lst
        self.template = ""
        
class Value:
    def __init__(self, name, vmin, vmax, vtyp):
        self.name = name
        self.vmin = vmin
        self.vmax = vmax
        self.vtyp = vtyp
        
    def isPass(self, val):
        return False
        
    
   # def addEnumParam(self, name, param_list):
        
        
    
   