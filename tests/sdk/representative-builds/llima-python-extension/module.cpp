#include <Python.h>

static PyModuleDef representative_module = {
    PyModuleDef_HEAD_INIT,
    "representative_llima_python",
    nullptr,
    -1,
    nullptr,
};

PyMODINIT_FUNC PyInit_representative_llima_python() {
  return PyModule_Create(&representative_module);
}
