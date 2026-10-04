bl_info = {'name': 'Base Support', 'author': 'Ricardo Lugaresi', 'version': (1, 0, 0),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > Base Support',
           'description': 'Analiza cómo apoya la figura y le hace una base plana, una peana o la gira a su mejor apoyo',
           'category': 'Object'}
import bpy
from . import common, support

SHAPES = [('CIRCLE', 'Redonda', ''), ('OVAL', 'Ovalada', ''), ('SQUARE', 'Cuadrada', 'Esquinas redondeadas'), ('HEX', 'Hexagonal', '')]
ICON = {'ok': 'CHECKMARK', 'warn': 'ERROR', 'bad': 'CANCEL'}


class BaseSupportProps(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades', items=common.UNIT_ITEMS, default='AUTO')
    cut_mm: bpy.props.FloatProperty(name='Corte (mm)', description='Cuánto se recorta desde el punto más bajo', default=0.6, min=0.05, max=20, precision=2)
    drop: bpy.props.BoolProperty(name='Bajar a la cama (Z = 0)', default=True)
    shape: bpy.props.EnumProperty(name='Forma', items=SHAPES, default='CIRCLE')
    height_mm: bpy.props.FloatProperty(name='Alto (mm)', default=3.0, min=0.6, max=50, precision=1)
    margin_mm: bpy.props.FloatProperty(name='Borde (mm)', description='Lo que sobresale la peana alrededor de los pies', default=4.0, min=0, max=100, precision=1)
    chamfer_mm: bpy.props.FloatProperty(name='Chaflán (mm)', default=0.8, min=0, max=10, precision=1)
    join: bpy.props.BoolProperty(name='Unida a la figura', description='Si no, la peana sale como pieza aparte', default=True)
    r_model: bpy.props.StringProperty()
    r_verdict: bpy.props.StringProperty()
    r_text: bpy.props.StringProperty()
    r_lines: bpy.props.StringProperty()
    done: bpy.props.StringProperty()


def _model(context):
    try:
        return common.pick_model(context)
    except common.AddonError:
        return None


def _run(op, context, fn):
    try:
        return fn()
    except common.AddonError as exc:
        op.report({'ERROR'}, str(exc))
        return None


class OBJECT_OT_base_support_analyze(bpy.types.Operator):
    """Mira dónde apoya la figura, cuánto y si es estable"""
    bl_idname = 'object.base_support_analyze'; bl_label = 'Analizar apoyo'; bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.base_support_props
        obj = _model(context)
        if obj is None:
            self.report({'ERROR'}, 'Selecciona el modelo'); return {'CANCELLED'}
        r = _run(self, context, lambda: support.analyze(context, obj, p.model_unit))
        if r is None:
            return {'CANCELLED'}
        p.r_model, p.r_verdict, p.r_text = obj.name, r['verdict'], r['text']
        lines = [f"Contacto con la cama: {r['contact_area']:.0f} mm² en {r['zones']} zona(s)",
                 f"Huella del modelo: {r['foot_area']:.0f} mm² · alto {r['height']:.0f} mm",
                 ('Centro de gravedad dentro del apoyo' if r['margin'] >= 0 else 'Centro de gravedad FUERA del apoyo')
                 + (f" ({r['margin']:.1f} mm)" if r['margin'] != float('inf') else ''),
                 f"Base plana recomendada: cortar {r['suggest_cut']:.1f} mm"]
        p.r_lines = '\n'.join(lines)
        p.cut_mm = r['suggest_cut']
        p.done = ''
        return {'FINISHED'}


class OBJECT_OT_base_support_flat(bpy.types.Operator):
    """Corta a ras por abajo para que apoye plano y firme"""
    bl_idname = 'object.base_support_flat'; bl_label = 'Base plana'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.base_support_props
        obj = _model(context)
        out = _run(self, context, lambda: support.flat_base(context, obj, p.cut_mm, p.model_unit, p.drop))
        if out is None:
            return {'CANCELLED'}
        p.done = f'{out.name}: base plana (corte de {p.cut_mm:.2f} mm)'
        bpy.ops.object.base_support_analyze()
        p.done = f'{out.name}: base plana (corte de {p.cut_mm:.2f} mm)'
        return {'FINISHED'}


class OBJECT_OT_base_support_plinth(bpy.types.Operator):
    """Crea una peana bajo la figura"""
    bl_idname = 'object.base_support_plinth'; bl_label = 'Crear peana'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.base_support_props
        obj = _model(context)
        out = _run(self, context, lambda: support.plinth(context, obj, p.shape, p.height_mm, p.margin_mm,
                                                          p.chamfer_mm, None, p.join, p.model_unit))
        if out is None:
            return {'CANCELLED'}
        p.done = f'{out.name}: peana creada'
        return {'FINISHED'}


class OBJECT_OT_base_support_orient(bpy.types.Operator):
    """Gira la figura para que apoye sobre su cara plana más grande sin volcar"""
    bl_idname = 'object.base_support_orient'; bl_label = 'Mejor apoyo'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.base_support_props
        obj = _model(context)
        res = _run(self, context, lambda: support.best_orientation(context, obj, p.model_unit))
        if res is None:
            return {'CANCELLED'}
        out, angle = res
        bpy.ops.object.base_support_analyze()
        p.done = f'{out.name}: girada {angle:.0f}°'
        return {'FINISHED'}


class VIEW3D_PT_base_support(bpy.types.Panel):
    bl_label = 'Base Support'; bl_idname = 'VIEW3D_PT_base_support'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Base Support'

    def draw(self, context):
        layout = self.layout; p = context.scene.base_support_props
        if common.draw_mode_warning(layout, context):
            return
        model = _model(context)
        box = layout.box()
        box.label(text='1 · Apoyo', icon='MESH_DATA')
        if model is None:
            r = box.row(); r.alert = True; r.label(text='Selecciona la figura', icon='ERROR')
        else:
            box.label(text=model.name, icon='OBJECT_DATA')
        col = box.column(); col.scale_y = 1.4
        col.operator('object.base_support_analyze', icon='VIEWZOOM')
        if model is not None and p.r_model == model.name and p.r_text:
            r = box.row(); r.alert = p.r_verdict == 'bad'
            r.label(text=p.r_text, icon=ICON.get(p.r_verdict, 'INFO'))
            c = box.column(align=True); c.scale_y = .8
            for line in p.r_lines.split('\n'):
                c.label(text='· ' + line)

        box = layout.box()
        box.label(text='2 · Base plana', icon='MOD_EDGESPLIT')
        box.prop(p, 'cut_mm'); box.prop(p, 'drop')
        col = box.column(); col.scale_y = 1.3
        col.operator('object.base_support_flat', icon='MOD_EDGESPLIT')

        box = layout.box()
        box.label(text='3 · Peana', icon='MESH_CYLINDER')
        r = box.row(); r.prop(p, 'shape', expand=True)
        box.prop(p, 'height_mm'); box.prop(p, 'margin_mm'); box.prop(p, 'chamfer_mm'); box.prop(p, 'join')
        col = box.column(); col.scale_y = 1.3
        col.operator('object.base_support_plinth', icon='MESH_CYLINDER')

        box = layout.box()
        box.label(text='4 · Girar a su mejor apoyo', icon='ORIENTATION_GIMBAL')
        box.operator('object.base_support_orient', icon='ORIENTATION_GIMBAL')
        if p.done:
            layout.label(text=p.done, icon='CHECKMARK')


classes = (BaseSupportProps, OBJECT_OT_base_support_analyze, OBJECT_OT_base_support_flat, OBJECT_OT_base_support_plinth,
           OBJECT_OT_base_support_orient, VIEW3D_PT_base_support)


def register():
    common.register_classes(classes, 'base_support_props', BaseSupportProps)


def unregister():
    common.unregister_classes(classes, 'base_support_props')
