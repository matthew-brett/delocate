testing-files: testing-wheels testing-libs

testing-wheels:
	(set -e && cd wheel_makers && sh make_wheels.sh)

testing-libs:
	(set -e && cd delocate/tests/data && sh make_libs.sh)
