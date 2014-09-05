import numpy as np
from utils.errors import UserInputError

class TRS(object):
    def __init__(self, defn, data):
        self.defn = defn.upper()
        if self.defn == "WLF":
            # check data
            if data.shape[0] != 3:
                raise UserInputError("expected 3 WLF parameters")
            self._data = np.array(data)

    @property
    def data(self):
        return self._data

    @property
    def temp_ref(self):
        return self._data[0]

    @property
    def wlf_coeffs(self):
        return self._data[1:]
