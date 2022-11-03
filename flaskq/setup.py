# -*- coding: utf-8 -*-

import os
from setuptools import setup, find_packages

VERSION='0.9'

setup(name='pytq',
      version=VERSION,
      packages=find_packages(),
      author='Raynald de Lahondes',
      author_email='raynald.delahondes@gmt.bio',
      license='LGPLv3',
      url='https://gmt.bio/',
      download_url='https://forge.gmt.bio/plugins/git/pytq/pytq',
      platforms=['GNU/Linux', 'BSD', 'MacOSX'],
      keywords=['task','queue','distributed'],
      description="distributed task queue for worker on heteroclyte nodes",
      include_package_data=True,
      package_data={
          'pytq': ['templates/*','css/*'],
      },
      zip_safe=False,
      install_requires=['Flask',
        'sqlalchemy',
        'flask-sqlalchemy',
        'flask-restx',
        'flask-socketio',
        'requests',
        'psutil',
        'tabulate',
        'psycopg2-binary',
        'boto3',
        'awscli',
        'awscli-plugin-endpoint',
        ],
      entry_points={
        'console_scripts': ['pytq-worker=pytq.client:main','pytq-launch=pytq.launch:main','pytq-manage=pytq.manage:main']
    },
     )
