<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44.0" styleCategories="Symbology|Labeling|Fields|Forms" labelsEnabled="0">
  <renderer-v2 type="categorizedSymbol" attr="estado" forceraster="0" symbollevels="0" enableorderby="0" referencescale="-1">
    <categories>
      <category value="funcional" symbol="0" label="Funcional" render="true" type="string"/>
      <category value="mantenimiento" symbol="1" label="En mantenimiento" render="true" type="string"/>
      <category value="averiada" symbol="2" label="Averiada" render="true" type="string"/>
    </categories>
    <symbols>
      <symbol type="marker" name="0" alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0">
        <layer class="SimpleMarker" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="color" value="255,214,0,255"/>
            <Option type="QString" name="outline_color" value="120,100,0,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="size" value="2.6"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="angle" value="0"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="offset_unit" value="MM"/>
            <Option type="QString" name="scale_method" value="diameter"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="1" alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0">
        <layer class="SimpleMarker" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="color" value="255,140,0,255"/>
            <Option type="QString" name="outline_color" value="120,60,0,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="size" value="2.6"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="angle" value="0"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="offset_unit" value="MM"/>
            <Option type="QString" name="scale_method" value="diameter"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="2" alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0">
        <layer class="SimpleMarker" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="color" value="200,30,30,255"/>
            <Option type="QString" name="outline_color" value="90,0,0,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="size" value="2.6"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="angle" value="0"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="offset_unit" value="MM"/>
            <Option type="QString" name="scale_method" value="diameter"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
    <source-symbol>
      <symbol type="marker" name="0" alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0">
        <layer class="SimpleMarker" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="color" value="255,214,0,255"/>
            <Option type="QString" name="outline_color" value="120,100,0,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="size" value="2.6"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="angle" value="0"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="offset_unit" value="MM"/>
            <Option type="QString" name="scale_method" value="diameter"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
          </Option>
        </layer>
      </symbol>
    </source-symbol>
  </renderer-v2>
  <aliases>
    <alias field="id" name="Identificador"/>
    <alias field="campus_id" name="Campus"/>
    <alias field="codigo" name="Código"/>
    <alias field="estado" name="Estado"/>
    <alias field="potencia" name="Potencia (W)"/>
  </aliases>
  <editable>
    <field name="id" editable="0"/>
    <field name="campus_id" editable="0"/>
    <field name="codigo" editable="1"/>
    <field name="estado" editable="1"/>
    <field name="potencia" editable="1"/>
  </editable>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>0</layerGeometryType>
</qgis>
