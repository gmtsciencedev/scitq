from . import fetch
import os

class URI:
    '''A small abstract class to manipulate URI like Path in pathlib'''
    def __init__(self, uri: str, proto: str=None):
        if ':' not in uri:
            self.path=uri
            uri=f'file://{uri}'
        else:
            self.proto=fetch.check_uri(uri) if proto is None else proto
        self.uri=uri
    
    def __truediv__(self, other: str) -> 'URI':
        while other.startswith('/'):
            other=other[1:]
        if '://' in other:
            raise fetch.UnsupportedError(f'Cannot join path with {other} which looks like a complete URI')
        return URI(os.path.join(self.uri, other), proto=self.proto)
    
    def __add__(self, other: str) -> str:
        return self.uri + other
    
    def __str__(self):
        return self.uri
    
    def __repr__(self):
        return f'URI("{self.uri}")'

    @property
    def path(self):
        return self.uri.split('://')[1]

    @property
    def info(self):
        return fetch.info(self.uri)

    def list(self):
        return fetch.list_content(self.uri)

    def exists(self):
        try:
            self.info
            return True
        except fetch.FetchErrorNoRepeat:
            return False

    def check_type(self, file_type):
        try:
            info=self.info
            if info.type=='unknown':
                raise fetch.FetchErrorNoRepeat('Unknown type of object')
            return info.type==file_type
        except:
            return False
    
    def isfile(self):
        return self.check_type('file')
    
    def isdir(self):
        return self.check_type('dir')
        