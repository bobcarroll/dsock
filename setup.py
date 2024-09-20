
from setuptools import setup, find_packages

setup(name='dsock',
      version='0.1',
      description='File-based socket server',
      author='Bob Carroll',
      author_email='bob.carroll@alum.rit.edu',
      packages=find_packages(include=['dsock']),
      classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Environment :: No Input/Output (Daemon)',
        'Framework :: AsyncIO',
        'Intended Audience :: Developers',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX :: Linux',
        'Environment :: Win32 (MS Windows)',
        'Programming Language :: Python :: 3',
        'Topic :: System :: Networking'])
