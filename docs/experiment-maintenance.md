# Bounded intelligence experiments

The 0.1.16 maintenance batch starts by making failed experiments inspectable.
Manual diagnostic runs must retain responses before validating them, bind the
selected engine and source identities, and report incomplete observations without
a quality verdict. Runtime work runs on disposable GitHub Actions runners.

The infrastructure is being introduced with online failing controls before its
implementation. Existing normal CI gates and release checks remain required.
