from setuptools import setup, find_packages

setup(
    name='comet-pt100',
    version='0.1.0',
    author="Bernhard Arnold",
    author_email="bernhard.arnold@oeaw.ac.at",
    packages=find_packages(exclude=['tests']),
    install_requires=[
        'comet @ https://github.com/hephy-dd/comet/archive/ui.zip#egg=comet-0.3.0',
    ],
    entry_points={
        'gui_scripts': [
            'comet-pt100 = comet_pt100:main',
        ],
    },
    test_suite='tests',
    license="GPLv3",
)
