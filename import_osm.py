import os
import math
import xml.etree.ElementTree as etree
from bpy_extras.io_utils import ImportHelper
import bpy
import bmesh
bl_info = {
    "name": "Import OpenStreetMap (.osm)",
    "author": "@lapka_td",
    "version": (1, 1, 1),
    "blender": (2, 77, 0),
    "location": "File > Import > OpenStreetMap (.osm)",
    "description": "Import a file in the OpenStreetMap format (.osm)",
    "url": 'https://github.com/olesya-wo/osm-import',
    "wiki_url": "https://github.com/olesya-wo/osm-import/wiki",
    "tracker_url": "https://github.com/olesya-wo/osm-import/issues",
    "support": "COMMUNITY",
    "category": "Import-Export"
}


def extrude_mesh(bm, thickness):
    geom = bmesh.ops.extrude_face_region(bm, geom=bm.faces)
    verts_extruded = [v for v in geom["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=verts_extruded, vec=(0, 0, thickness))


def extrude_edges(bm, thickness):
    geom = bmesh.ops.extrude_face_region(bm, geom=bm.edges)
    verts_extruded = [v for v in geom["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=verts_extruded, vec=(0, 0, thickness))


def assign_materials(obj, materialname, color, faces):
    if bpy.data.materials.get(materialname) is not None:
        mat = bpy.data.materials[materialname]
    else:
        # create material
        mat = bpy.data.materials.new(name=materialname)
        mat.diffuse_color = color

    matidx = len(obj.data.materials)
    obj.data.materials.append(mat)

    for face in faces:
        face.material_index = matidx


def parse_scalar_and_unit(htag):
    # TODO add float support
    # TODO add unit conversion
    for i, c in enumerate(htag):
        if not c.isdigit():
            return int(htag[:i]), htag[i:].strip()
    return int(htag), ""


class OsmParser(bpy.types.Operator, ImportHelper):
    """Import a file in the OpenStreetMap format (.osm)"""
    nodes = {}
    curr_way = None
    node_tags = set()  # which tags store in the node
    radius = 6378137
    lat = 0
    lon = 0
    latInRadians = 0
    bounds = None
    bl_idname = "import_scene.osm"
    bl_label = "Import OpenStreetMap"
    bl_options = {"REGISTER"}
    filename_ext = ".osm"

    filter_glob = bpy.props.StringProperty(
        default="*.osm",
        options={"HIDDEN"},
    )

    importBuildings = bpy.props.BoolProperty(
        name="Import buildings",
        description="Import building outlines",
        default=True,
    )

    importNaturals = bpy.props.BoolProperty(
        name="Import naturals",
        description="Import natural outlines",
        default=True,
    )

    importHighways = bpy.props.BoolProperty(
        name="Import roads and paths",
        description="Import roads and paths",
        default=False,
    )

    importBarriers = bpy.props.BoolProperty(
        name="Import barriers",
        description="Import barriers",
        default=True,
    )

    importLanduse = bpy.props.BoolProperty(
        name="Import landuse",
        description="Import landuse",
        default=True,
    )

    def from_geo(self, lat, lon):
        lat = math.radians(lat)
        lon = math.radians(lon - self.lon)
        b = math.sin(lon) * math.cos(lat)
        x = 0.5 * self.radius * math.log((1 + b) / (1 - b))
        y = self.radius * (math.atan(math.tan(lat) / math.cos(lon)) - self.latInRadians)
        return x, y

    def parse(self, filename):
        xml_f = open(filename, encoding="UTF-8")
        self.nodes = {}
        self.curr_way = None
        stage = 0  # 0 - need osm, 1 - in osm, 2 - in node, 3 - in way, 4 - in relation
        last_node = None
        context = etree.iterparse(xml_f, events=('start',))
        context = iter(context)
        _, root = next(context)
        for event, elem in context:
            # processing
            if elem.tag == "osm":
                stage = 1
            elif elem.tag == "node":
                stage = 2
                if last_node:
                    if len(last_node["tags"]) == 0:
                        last_node["tags"] = None
                    self.nodes[last_node["id"]] = (last_node["lat"], last_node["lon"], last_node["tags"])
                last_node = {"id": int(elem.attrib.get("id")),
                             "lat": float(elem.attrib.get("lat")),
                             "lon": float(elem.attrib.get("lon")),
                             "tags": {}}
            elif elem.tag == "way":
                stage = 3
                if last_node:
                    if len(last_node["tags"]) == 0:
                        last_node["tags"] = None
                    self.nodes[last_node["id"]] = (last_node["lat"], last_node["lon"], last_node["tags"])
                    last_node = None
                if self.curr_way:
                    self.way_handler()
                self.curr_way = {"id": elem.attrib.get("id"), "nodes": [], "tags": {}}
            elif elem.tag == "relation":
                stage = 4
                if self.curr_way:
                    self.way_handler()
                    self.curr_way = None
            elif elem.tag == "bounds":
                stage = 1
                self.bounds = {
                    "minLat": float(elem.attrib.get("minlat")),
                    "minLon": float(elem.attrib.get("minlon")),
                    "maxLat": float(elem.attrib.get("maxlat")),
                    "maxLon": float(elem.attrib.get("maxlon"))
                }
                self.lat = (self.bounds["minLat"] + self.bounds["maxLat"]) * 0.5
                self.lon = (self.bounds["minLon"] + self.bounds["maxLon"]) * 0.5
                self.latInRadians = math.radians(self.lat)
            elif elem.tag == "tag":
                if stage == 2:
                    k = elem.attrib.get("k")
                    if k in self.node_tags:
                        last_node["tags"][k] = elem.attrib.get("v")
                elif stage == 3:
                    k = elem.attrib.get("k")
                    self.curr_way["tags"][k] = elem.attrib.get("v")
                elif stage == 4:
                    pass  # skip
                else:
                    print("Error in tag structure! Stage:", stage, "Tag:", elem.tag)
                    break
            elif elem.tag == "nd":
                self.curr_way["nodes"].append(int(elem.attrib.get("ref")))
            elif elem.tag == "member":
                pass  # skip
            else:
                print("Unknown tag:", elem.tag)
                break
            # cleaning
            elem.clear()
            root.clear()
        xml_f.close()

    # Handlers for generate geometry
    def handler_buildings(self):
        way_nodes = self.curr_way["nodes"]
        nodes_count = len(way_nodes) - 1
        # a polygon must have at least 3 vertices
        if nodes_count < 3:
            return
        tags = self.curr_way["tags"]
        # compose object name
        name = self.curr_way["id"]
        if "addr:housenumber" in tags and "addr:street" in tags:
            name = tags["addr:street"] + ", " + tags["addr:housenumber"]
        elif "name" in tags:
            name = tags["name"]

        bm = bmesh.new()
        verts = []
        for i in range(nodes_count):
            node = self.nodes[way_nodes[i]]
            v = self.from_geo(node[0], node[1])
            verts.append(bm.verts.new((v[0], v[1], 0)))

        bm.faces.new(verts)

        thickness = 0
        if "height" in tags:
            thickness, unit = parse_scalar_and_unit(tags["height"])
        elif "building:levels" in tags:
            thickness, unit = parse_scalar_and_unit(tags["building:levels"])
            thickness *= 3
        else:
            thickness = 3
        if thickness > 0:
            extrude_mesh(bm, thickness)

        bm.normal_update()
        mesh = bpy.data.meshes.new(self.curr_way["id"])
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.objects.link(obj)
        obj.select = True
        for key in tags:
            obj[key] = tags[key]
        assign_materials(obj, "roof", (1.0, 0.0, 0.0), [mesh.polygons[0]])
        assign_materials(obj, "building", (1, 0.7, 0.0), mesh.polygons[1:])

    def handler_building_parts(self):
        way_nodes = self.curr_way["nodes"]
        nodes_count = len(way_nodes) - 1
        # a polygon must have at least 3 vertices
        if nodes_count < 3:
            return
        tags = self.curr_way["tags"]
        # compose object name
        name = self.curr_way["id"]
        if "addr:housenumber" in tags and "addr:street" in tags:
            name = tags["addr:street"] + ", " + tags["addr:housenumber"]
        elif "name" in tags:
            name = tags["name"]

        min_height = 0
        height = 0
        if "min_height" in tags:
            min_height, unit = parse_scalar_and_unit(tags["min_height"])
        if "height" in tags:
            height, unit = parse_scalar_and_unit(tags["height"])
        if min_height == 0 and height == 0 and "building:levels" in tags:
            height, unit = parse_scalar_and_unit(tags["building:levels"])
            height *= 3

        bm = bmesh.new()
        verts = []
        for i in range(nodes_count):
            node = self.nodes[way_nodes[i]]
            v = self.from_geo(node[0], node[1])
            verts.append(bm.verts.new((v[0], v[1], min_height)))
        bm.faces.new(verts)
        # extrude
        if (height - min_height) > 0:
            extrude_mesh(bm, (height - min_height))
        bm.normal_update()
        mesh = bpy.data.meshes.new(self.curr_way["id"])
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.objects.link(obj)
        obj.select = True
        for key in tags:
            obj[key] = tags[key]

    def handler_highways(self):
        way_nodes = self.curr_way["nodes"]
        nodes_count = len(way_nodes)
        # a way must have at least 2 vertices
        if nodes_count < 2:
            return
        tags = self.curr_way["tags"]
        name = tags["name"] if "name" in tags else self.curr_way["id"]
        bm = bmesh.new()
        prev_vertex = None
        for i in range(nodes_count):
            node = self.nodes[way_nodes[i]]
            v = self.from_geo(node[0], node[1])
            v = bm.verts.new((v[0], v[1], 0))
            if prev_vertex:
                bm.edges.new([prev_vertex, v])
            prev_vertex = v

        mesh = bpy.data.meshes.new(self.curr_way["id"])
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.objects.link(obj)
        obj.select = True
        for key in tags:
            obj[key] = tags[key]

    def handler_barrier(self):
        way_nodes = self.curr_way["nodes"]
        nodes_count = len(way_nodes)
        # a wall must have at least 2 vertices
        if nodes_count < 2:
            return
        tags = self.curr_way["tags"]
        name = tags["name"] if "name" in tags else self.curr_way["id"]
        bm = bmesh.new()
        prev_vertex = None
        for i in range(nodes_count):
            node = self.nodes[way_nodes[i]]
            v = self.from_geo(node[0], node[1])
            v = bm.verts.new((v[0], v[1], 0))
            if prev_vertex:
                bm.edges.new([prev_vertex, v])
            prev_vertex = v

        height = 0
        if "height" in tags:
            height, unit = parse_scalar_and_unit(tags["height"])
        # extrude
        if height > 0:
            extrude_edges(bm, height)
        else:
            extrude_edges(bm, 0.5)

        bm.normal_update()
        mesh = bpy.data.meshes.new(self.curr_way["id"])
        bm.to_mesh(mesh)

        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.objects.link(obj)
        obj.select = True
        for key in tags:
            obj[key] = tags[key]
        assign_materials(obj, tags["barrier"], (0.0, 0.0, 1.0), [])

    def handler_naturals(self):
        way_nodes = self.curr_way["nodes"]
        nodes_count = len(way_nodes)
        if nodes_count == 1:
            # This is some point "natural".
            # which we ignore for now (trees, etc.)
            pass
        nodes_count = nodes_count - 1
        # a polygon must have at least 3 vertices
        if nodes_count < 3:
            return
        tags = self.curr_way["tags"]
        name = self.curr_way["id"]
        if "name" in tags:
            name = tags["name"]
        bm = bmesh.new()
        verts = []
        for i in range(nodes_count):
            node = self.nodes[way_nodes[i]]
            v = self.from_geo(node[0], node[1])
            verts.append(bm.verts.new((v[0], v[1], 0)))
        bm.faces.new(verts)
        bm.normal_update()
        mesh = bpy.data.meshes.new(self.curr_way["id"])
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.objects.link(obj)
        obj.select = True
        for key in tags:
            obj[key] = tags[key]
        natural_type = tags["natural"]
        color = (0.5, 0.5, 0.5)

        if natural_type == "water":
            color = (0, 0, 1)
        assign_materials(obj, natural_type, color, [mesh.polygons[0]])

    def handler_landuse(self):
        way_nodes = self.curr_way["nodes"]
        nodes_count = len(way_nodes)
        nodes_count = nodes_count - 1
        # a polygon must have at least 3 vertices
        if nodes_count < 3:
            return
        tags = self.curr_way["tags"]
        name = self.curr_way["id"]
        if "name" in tags:
            name = tags["name"]
        bm = bmesh.new()
        verts = []
        for i in range(nodes_count):
            node = self.nodes[way_nodes[i]]
            v = self.from_geo(node[0], node[1])
            verts.append(bm.verts.new((v[0], v[1], 0)))
        bm.faces.new(verts)
        bm.normal_update()
        mesh = bpy.data.meshes.new(self.curr_way["id"])
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.objects.link(obj)
        obj.select = True
        for key in tags:
            obj[key] = tags[key]
        natural_type = tags["landuse"]
        color = (0.5, 0.5, 0.5)
        if natural_type == "grass":
            color = (0, 1, 0)
        assign_materials(obj, natural_type, color, [mesh.polygons[0]])

    def get_handler(self):
        # https://wiki.openstreetmap.org/wiki/Map_Features
        if not self.curr_way:
            return None
        if self.curr_way["tags"].get("building", None) and self.importBuildings:
            return self.handler_buildings
        if self.curr_way["tags"].get("building:part", None) and self.importBuildings:
            return self.handler_building_parts
        if self.curr_way["tags"].get("highway", None) and self.importHighways:
            return self.handler_highways
        if self.curr_way["tags"].get("barrier", None) and self.importBarriers:
            return self.handler_barrier
        if self.curr_way["tags"].get("natural", None) and self.importNaturals:
            return self.handler_naturals
        if self.curr_way["tags"].get("landuse", None) and self.importLanduse:
            return self.handler_landuse
        return None

    def way_handler(self):
        handler = self.get_handler()
        if handler:
            handler()

    def execute(self, context):
        bpy.ops.object.select_all(action="DESELECT")
        name = os.path.basename(self.filepath)

        bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
        parent_object = context.active_object
        parent_object.name = name

        self.parse(self.filepath)
        bpy.context.scene.update()

        context.scene.objects.active = parent_object
        bpy.ops.object.parent_set()

        bpy.ops.object.select_all(action="DESELECT")
        return {"FINISHED"}


def menu_func_import(self, context):
    self.layout.operator(OsmParser.bl_idname, text="OpenStreetMap (.osm)")


def register():
    bpy.utils.register_class(OsmParser)
    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_class(OsmParser)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == "__main__":
    register()
