#!/bin/sh
python -m build --sdist --wheel
twine upload dist/*
