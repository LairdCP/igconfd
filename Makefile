IGCONFD_EGG = dist/igconfd-1.0-py2.7.egg
IGCONFD_PY_SRCS = __main__.py gattsvc.py wifisvc.py
IGCONFD_PY_SETUP = setup.py

all: $(IGCONFD_EGG)

$(IGCONFD_EGG): $(IGCONFD_PY_SRCS) $(IGCONFD_PY_SETUP)
	$(PYTHON) $(IGCONFD_PY_SETUP) bdist_egg --exclude-source-files

.PHONY: clean

clean:
	-rm -rf dist
	-rm -rf build
	-rm -rf *.egg-info
