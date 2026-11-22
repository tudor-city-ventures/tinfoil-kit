# shellcheck shell=bash
# The mock internet's addresses (tests/mock_remote.py on port 19000), for the end-to-end and drive tests: every
# remote endpoint the kit uses can be pointed elsewhere by its KIT_* variable.
export KIT_KIWIX_CATALOG="http://127.0.0.1:19000/catalog/v2/entries?count=-1"
export KIT_KIWIX_RELEASES="http://127.0.0.1:19000/release/{product}/"
export KIT_GITHUB_API="http://127.0.0.1:19000"
export KIT_HF="http://127.0.0.1:19000"
export KIT_ADOPTIUM_API="http://127.0.0.1:19000/adoptium"
export KIT_MAVEN="http://127.0.0.1:19000/maven"
export KIT_NPM="http://127.0.0.1:19000/npm"
export KIT_GITHUB_WEB="http://127.0.0.1:19000/ghweb"
export KIT_PROTOMAPS_BUILDS="http://127.0.0.1:19000/protomaps/builds.json"
export KIT_PROTOMAPS_BUILD_BASE="http://127.0.0.1:19000/protomaps"
export KIT_PHOTON_DUMPS="http://127.0.0.1:19000/photon/"
export KIT_GEOFABRIK="http://127.0.0.1:19000/geofabrik"
