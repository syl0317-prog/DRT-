"""Explicit key-free web basemaps, attribution, and client-side load diagnostics."""
import folium
from branca.element import MacroElement, Template

OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
PROVIDERS = (
    dict(name="OpenStreetMap 표준", url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
         attribution=OSM_ATTRIBUTION, max_zoom=19),
    dict(name="OSM Deutschland (연구·비상업용)", url="https://tile.openstreetmap.de/{z}/{x}/{y}.png",
         attribution=OSM_ATTRIBUTION + ' · <a href="https://openstreetmap.de/germanstyle/">OSM Deutschland / FOSSGIS e.V.</a>', max_zoom=18),
)


class TileLoadNotice(MacroElement):
    """Observe real image events; no proxy, retries, downloads, or header spoofing."""
    _template = Template(r"""
    {% macro script(this, kwargs) %}
    (function () {
        var map = {{ this._parent.get_name() }};
        var layers = [{% for layer in this.layers %}{{ layer.get_name() }}{{ ',' if not loop.last }}{% endfor %}];
        var state = layers.map(function () { return {loaded: 0, errors: new Set(), waited: false}; });
        var control = L.control({position: 'bottomleft'});
        var notice;
        control.onAdd = function () {
            notice = L.DomUtil.create('div', 'basemap-load-notice');
            notice.setAttribute('role', 'status');
            notice.style.cssText = 'display:none;background:#fff3cd;color:#664d03;padding:8px;max-width:290px;border:1px solid #e0ba52;border-radius:5px;font-size:12px';
            L.DomEvent.disableClickPropagation(notice);
            return notice;
        };
        control.addTo(map);
        function update() {
            var index = layers.findIndex(function (layer) { return map.hasLayer(layer); });
            if (index < 0) return;
            var current = state[index];
            var message = current.errors.size ? '배경지도 타일 로딩 실패: 차단 또는 통신 오류일 수 있습니다. 레이어에서 다른 제공자를 선택하거나 네트워크를 확인하세요.' :
                current.waited && !current.loaded ? '배경지도 로딩이 지연됩니다. 네트워크 또는 지도 제공자 상태를 확인하세요.' : '';
            notice.textContent = message;
            notice.style.display = message ? 'block' : 'none';
        }
        layers.forEach(function (layer, index) {
            layer.on('tileerror', function (event) { state[index].errors.add(event.tile.src); update(); });
            layer.on('tileload', function (event) { state[index].loaded++; state[index].errors.delete(event.tile.src); update(); });
            layer.on('add', function () {
                state[index] = {loaded: 0, errors: new Set(), waited: false};
                setTimeout(function () { state[index].waited = true; update(); }, 15000);
            });
        });
        map.on('baselayerchange', update);
        setTimeout(function () { state.forEach(function (s) { s.waited = true; }); update(); }, 15000);
    })();
    {% endmacro %}
    """)

    def __init__(self, layers):
        super().__init__()
        self._name = "TileLoadNotice"
        self.layers = layers


def background_map(location, zoom_start=14, layer_control=True, **kwargs):
    layers = [folium.TileLayer(tiles=p["url"], name=p["name"], attr=p["attribution"],
                              max_zoom=p["max_zoom"], show=i == 0,
                              **{"referrerPolicy": "strict-origin-when-cross-origin"})
              for i, p in enumerate(PROVIDERS)]
    result = folium.Map(location=location, zoom_start=zoom_start, tiles=layers[0], **kwargs)
    layers[1].add_to(result)  # Not requested until the user selects this base layer.
    result.get_root().header.add_child(folium.Element(
        '<meta name="referrer" content="strict-origin-when-cross-origin">'))
    TileLoadNotice(layers).add_to(result)
    if layer_control:
        folium.LayerControl(collapsed=True).add_to(result)
    return result
