
from setuptools import setup, find_packages

with open('README.md', 'r') as f:
    long_description = f.read()

setup(name='dsock',
      version='0.5',
      description='File-based socket server',
      long_description=long_description,
      long_description_content_type='text/markdown',
      author='Bob Carroll',
      author_email='bob.carroll@alum.rit.edu',
      url='https://git.bobc.io/bobc/dsock',
      packages=find_packages(include=['dsock']),
      classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Environment :: No Input/Output (Daemon)',
        'Framework :: AsyncIO',
        'Intended Audience :: Developers',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3',
        'Topic :: System :: Networking'])
