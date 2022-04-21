TARGET_PYTHON_VERSION := $$(find $(TARGET_DIR)/usr/lib -maxdepth 1 -type d -name python* -printf "%f\n" | egrep -o '[0-9].[0-9]')
IGCONFD_EGG = dist/igconfd-1.0-py$(TARGET_PYTHON_VERSION).egg
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
