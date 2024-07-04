from sqlalchemy import and_
from sqlalchemy.orm.exc import NoResultFound
from ..server.model import Flavor, FlavorMetrics
from io import StringIO

import logging as log

def show_key(primary_keys, premary_key_values):
    return ','.join([f'{k}:{v}' for k,v in zip(primary_keys, premary_key_values)])

class GenericProvider:

    def __init__(self, session, provider):
        self.session = session
        self.provider = provider

    def push(self, x, cache=StringIO()):
        """A small wrapper on print with options"""
        if self.live:
            print(x, end='', flush=True)
        else:
            cache.write(x)
            if '\n' in x:
                log.warning(cache.getvalue())
                cache.seek(0)
                cache.truncate()

    def update_flavors(self, flavors):
        """Update an existing flavor or create a new one"""
        self.generic_update(object_class=Flavor,
                            current=flavors,
                            provider=self.provider,
                            attributes=['cpu','ram','disk','bandwidth', 'gpu', 'gpumem', 'tags'],
                            primary_keys=['provider','name'])

    def update_flavor_metrics(self, metrics):
        """Update some flavor metrics (e.g. regional details for a flavor)"""
        self.generic_update(object_class=FlavorMetrics,
                            current=metrics,
                            provider=self.provider,
                            attributes=['eviction','cost'],
                            primary_keys=['provider','flavor_name','region_name'])

    def generic_update(self, object_class, current, provider, attributes, primary_keys):
        """Compare a list of object of class object_class with its current content in base and update"""
        current_dict = { tuple ( (getattr(object,pk) for pk in primary_keys) ) : object for object in current }
        for object in self.session.query(object_class).filter(object_class.provider==provider).all():
            pkey = tuple( (getattr(object,pk) for pk in primary_keys) )
            if pkey not in current_dict:
                self.push(f'{object_class.__name__} {show_key(primary_keys,pkey)} is removed\n')
                self.session.delete(object)
            else:
                new_object = current_dict.pop(pkey)
                for attr in attributes:
                    val=getattr(object,attr)
                    new_val=getattr(new_object,attr)
                    if val!=new_val:
                        self.push(f'{object_class.__name__} {show_key(primary_keys,pkey)} update {attr}: {val}->{new_val}\n')
                        setattr(object, attr, new_val)
        for _,object in current_dict.items():
            pkey = tuple( (getattr(object,pk) for pk in primary_keys) )
            self.push(f'new {object_class.__name__} {show_key(primary_keys,pkey)}\n')
            self.session.add(object)
        self.session.commit()


