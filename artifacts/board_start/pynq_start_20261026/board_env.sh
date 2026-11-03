# Source from the extracted kit directory; no installation or system writes.
export BOARD_PY=/usr/local/share/pynq-venv/bin/python3
export XILINX_XRT=/usr
export PYTHONPATH="$PWD/software:/home/xilinx/lesion_fpga/.board_deps"
if [ ! -x "$BOARD_PY" ]; then
  echo "STOP: expected PYNQ Python is missing. Do not substitute/install packages blindly."
  return 1
fi
