from globaleaks import settings

class MacroOperation():
    def returnData(self, data):
        """
        Storm require copy of the return value, or the
        then the transact thread is closed, the stack
        would http://www.youtube.com/watch?v=C7JZ4F3zJdY fart.
        """
        if isinstance(data, list):
            self._data = list(data)
        elif isinstance(data, dict):
            self._data = dict(data)
        else:
            raise NotImplementedError

    def returnCode(self, http_code):
        self._http = http_code

    def prepareRetVals(self):
        returnDict = { 'code' : self._http }

        if hasattr(self, '_data' ):
            returnDict.update({ 'data' : self._data })

        return dict(returnDict)