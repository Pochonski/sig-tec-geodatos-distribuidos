<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44.0" styleCategories="Symbology|Labeling|Fields|Forms" labelsEnabled="1">
  <renderer-v2 type="singleSymbol" forceraster="0" symbollevels="0" enableorderby="0" referencescale="-1">
    <symbols>
      <symbol type="line" name="0" alpha="1" clip_to_extent="1" force_rhr="0" frame_rate="10" is_animated="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="84,84,84,255"/>
            <Option type="QString" name="line_width" value="1.6"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
            <Option type="QString" name="offset" value="0"/>
            <Option type="QString" name="offset_unit" value="MM"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fieldName="nombre" isExpression="0" fontFamily="Arial" fontSize="8" fontSizeUnit="Point" fontWeight="75" fontItalic="0" textColor="40,40,40,255" textOpacity="1" multilineHeight="1" allowHtml="0">
        <text-buffer bufferDraw="1" bufferSize="0.8" bufferSizeUnits="MM" bufferColor="255,255,255,255" bufferOpacity="0.9" bufferNoFill="1" bufferJoinStyle="128"/>
      </text-style>
      <text-format wrapChar="" multilineAlign="3" autoWrapLength="0" formatNumbers="0" decimals="0" plussign="0"/>
      <placement placement="2" dist="1" distUnits="MM" offsetType="0" priority="5" maxCurvedCharAngleIn="25" maxCurvedCharAngleOut="-25"/>
      <rendering scaleVisibility="0" obstacle="1" drawLabels="1" fontLimitPixelSize="0" upsidedownLabels="0" limitNumLabels="0"/>
    </settings>
  </labeling>
  <aliases>
    <alias field="id" name="Identificador"/>
    <alias field="campus_id" name="Campus"/>
    <alias field="nombre" name="Nombre"/>
    <alias field="tipo" name="Tipo"/>
    <alias field="superficie" name="Superficie"/>
  </aliases>
  <editable>
    <field name="id" editable="0"/>
    <field name="campus_id" editable="0"/>
    <field name="nombre" editable="1"/>
    <field name="tipo" editable="1"/>
    <field name="superficie" editable="1"/>
  </editable>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>1</layerGeometryType>
</qgis>
