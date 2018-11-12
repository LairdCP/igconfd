#!/usr/bin/python

from setuptools import setup

setup(name='igconfd',
      version='1.0',
      py_modules=['__main__','gattsvc','vspsvc','leadvert',
        'devmngr','messagemngr','netmngr','provmngr']
      )
