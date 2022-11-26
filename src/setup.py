# -*- coding: utf-8 -*-

import os
from setuptools import setup, find_packages

VERSION='1.0b2'

setup(name='scitq',
      version=VERSION,
      packages=find_packages(),
      author='Raynald de Lahondes',
      author_email='raynald.delahondes@gmt.bio',
      license='LGPLv3',
      url='https://gmt.bio/',
      download_url='https://forge.gmt.bio/plugins/git/scitq/scitq',
      platforms=['GNU/Linux', 'BSD', 'MacOSX'],
      keywords=['task','queue','distributed'],
      description="distributed task queue for worker on heteroclyte nodes",
      include_package_data=True,
      package_data={
          'scitq': ['templates/*','css/*'],
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
        'console_scripts': ['scitq-worker=scitq.client:main','scitq-launch=scitq.launch:main','scitq-manage=scitq.manage:main']
    },
     )
