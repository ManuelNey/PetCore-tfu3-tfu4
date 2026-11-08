from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr


SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
HISTORIAL_NS = "urn:petcore:historial"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("soap", SOAP_NS)
ET.register_namespace("h", HISTORIAL_NS)
ET.register_namespace("xsi", XSI_NS)


def crear_sobre(nombre_operacion: str):
    """Crea la estructura Envelope > Body > operación."""
    sobre = ET.Element(f"{{{SOAP_NS}}}Envelope")
    cuerpo = ET.SubElement(sobre, f"{{{SOAP_NS}}}Body")
    operacion = ET.SubElement(
        cuerpo,
        f"{{{HISTORIAL_NS}}}{nombre_operacion}",
    )

    return sobre, operacion


def agregar_dato(padre, nombre: str, valor):
    """Convierte diccionarios, listas y valores simples en XML."""
    elemento = ET.SubElement(
        padre,
        f"{{{HISTORIAL_NS}}}{nombre}",
    )

    if valor is None:
        elemento.set(f"{{{XSI_NS}}}nil", "true")

    elif isinstance(valor, dict):
        for clave, contenido in valor.items():
            agregar_dato(elemento, clave, contenido)

    elif isinstance(valor, list):
        for contenido in valor:
            agregar_dato(elemento, "item", contenido)

    elif isinstance(valor, bool):
        elemento.text = "true" if valor else "false"

    else:
        elemento.text = str(valor)

    return elemento


def convertir_a_xml(sobre) -> bytes:
    """Transforma la estructura XML en los bytes de la respuesta."""
    return ET.tostring(
        sobre,
        encoding="utf-8",
        xml_declaration=True,
    )


def leer_operacion(contenido: bytes):
    """Valida un mensaje SOAP 1.1 en UTF-8 y obtiene su operación."""
    if len(contenido) > 2_000_000:
        raise ValueError("El mensaje SOAP es demasiado grande.")

    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("El mensaje debe usar UTF-8.") from error

    texto_mayusculas = texto.upper()

    if (
        "<!DOCTYPE" in texto_mayusculas
        or "<!ENTITY" in texto_mayusculas
    ):
        raise ValueError(
            "El mensaje contiene declaraciones no permitidas."
        )

    sobre = ET.fromstring(texto)

    if sobre.tag != f"{{{SOAP_NS}}}Envelope":
        raise ValueError("Se esperaba un Envelope SOAP.")

    cuerpo = sobre.find(f"{{{SOAP_NS}}}Body")

    if cuerpo is None or len(cuerpo) != 1:
        raise ValueError(
            "El Body debe contener exactamente una operación."
        )

    return cuerpo[0]


def crear_error(mensaje: str, estado: int = 400) -> bytes:
    """Construye un SOAP Fault con el estado original en detail."""
    sobre, error = crear_sobre("Fault")
    error.tag = f"{{{SOAP_NS}}}Fault"

    ET.SubElement(error, "faultcode").text = (
        "soap:Client" if estado < 500 else "soap:Server"
    )
    ET.SubElement(error, "faultstring").text = mensaje

    detalle = ET.SubElement(error, "detail")
    ET.SubElement(detalle, "status").text = str(estado)

    return convertir_a_xml(sobre)


def generar_wsdl(direccion_servicio: str) -> str:
    """
    Genera el contrato: operación, parámetros, tipos de respuesta
    y dirección donde se realizan las llamadas SOAP.
    """

    def campo(
        nombre: str,
        tipo: str = "string",
        opcional: bool = False,
        nulo: bool = False,
    ) -> str:
        """Describe un campo dentro del esquema XML."""
        tipo_xml = tipo if ":" in tipo else f"xsd:{tipo}"
        atributos = f'name="{nombre}" type="{tipo_xml}"'

        if opcional:
            atributos += ' minOccurs="0"'

        if nulo:
            atributos += ' nillable="true"'

        return f"<xsd:element {atributos}/>"

    def tipo_complejo(
        nombre: str,
        campos: str,
        orden: str = "sequence",
    ) -> str:
        """Agrupa campos para describir un objeto."""
        return (
            f'<xsd:complexType name="{nombre}">'
            f"<xsd:{orden}>"
            f"{campos}"
            f"</xsd:{orden}>"
            "</xsd:complexType>"
        )

    def lista(nombre: str, tipo_elemento: str) -> str:
        """Describe una lista de elementos del mismo tipo."""
        return tipo_complejo(
            nombre,
            (
                '<xsd:element name="item" '
                f'type="{tipo_elemento}" '
                'minOccurs="0" maxOccurs="unbounded"/>'
            ),
        )

    campos_mascota = "".join(
        campo(nombre, tipo, nulo=nulo)
        for nombre, tipo, nulo in [
            ("id", "long", False),
            ("nombre", "string", False),
            ("especie", "string", False),
            ("raza", "string", True),
            ("fecha_nacimiento", "date", True),
            ("peso_actual", "double", True),
            ("propietario", "string", False),
            ("telefono", "string", False),
        ]
    )

    campos_correccion = "".join(
        campo(nombre, tipo, nulo=nulo)
        for nombre, tipo, nulo in [
            ("id", "long", False),
            ("fecha", "date", False),
            ("hora", "string", False),
            ("veterinario", "string", False),
            ("motivo_correccion", "string", False),
            ("diagnostico", "string", True),
            ("observaciones", "string", True),
            ("tratamiento", "string", True),
            ("recomendaciones", "string", True),
            ("vigente", "boolean", False),
        ]
    )

    # Incluye los campos de las distintas vistas del historial:
    # cliente, veterinario y consulta no recuperada.
    campos_consulta = "".join(
        campo(nombre, tipo, opcional=True, nulo=True)
        for nombre, tipo in [
            ("id", "long"),
            ("id_consulta", "long"),
            ("recuperada", "boolean"),
            ("mensaje", "string"),
            ("fecha", "date"),
            ("hora", "string"),
            ("tipo", "string"),
            ("veterinario", "string"),
            ("motivo", "string"),
            ("observaciones", "string"),
            ("diagnostico", "string"),
            ("tratamiento", "string"),
            ("recomendaciones", "string"),
            ("modificada_el", "dateTime"),
            ("edicion_vencida", "boolean"),
            ("corregida", "boolean"),
            ("corregida_el", "date"),
            ("correcciones", "tns:Correcciones"),
        ]
    )

    tipos = "".join(
        [
            tipo_complejo("Mascota", campos_mascota),
            tipo_complejo("Correccion", campos_correccion),
            lista("Correcciones", "tns:Correccion"),
            tipo_complejo(
                "Consulta",
                campos_consulta,
                orden="all",
            ),
            lista("Consultas", "tns:Consulta"),
            lista("Advertencias", "xsd:string"),
            tipo_complejo(
                "HistorialCliente",
                campo("total", "long")
                + campo("consultas", "tns:Consultas"),
            ),
            tipo_complejo(
                "HistorialVeterinario",
                campo("mascota", "tns:Mascota")
                + campo("consistente", "boolean")
                + campo("recuperadas", "long")
                + campo("esperadas", "long")
                + campo("ultimo_intento", "dateTime")
                + campo("advertencias", "tns:Advertencias")
                + campo("consultas", "tns:Consultas"),
            ),
        ]
    )

    parametros = (
        campo("id_mascota", "long")
        + campo("limite", "int", opcional=True)
        + campo("offset", "int", opcional=True)
        + campo("tipo", "string", opcional=True, nulo=True)
    )

    respuestas = (
        campo("cliente", "tns:HistorialCliente")
        + campo("veterinario", "tns:HistorialVeterinario")
    )

    direccion_xml = quoteattr(direccion_servicio)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<wsdl:definitions
    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:tns="{HISTORIAL_NS}"
    targetNamespace="{HISTORIAL_NS}"
    name="HistorialService">

    <wsdl:types>
        <xsd:schema
            targetNamespace="{HISTORIAL_NS}"
            elementFormDefault="qualified">

            {tipos}

            <xsd:element name="ObtenerHistorialMascota">
                <xsd:complexType>
                    <xsd:sequence>
                        {parametros}
                    </xsd:sequence>
                </xsd:complexType>
            </xsd:element>

            <xsd:element name="ObtenerHistorialMascotaResponse">
                <xsd:complexType>
                    <xsd:choice>
                        {respuestas}
                    </xsd:choice>
                </xsd:complexType>
            </xsd:element>

        </xsd:schema>
    </wsdl:types>

    <wsdl:message name="Entrada">
        <wsdl:part
            name="parameters"
            element="tns:ObtenerHistorialMascota"/>
    </wsdl:message>

    <wsdl:message name="Salida">
        <wsdl:part
            name="parameters"
            element="tns:ObtenerHistorialMascotaResponse"/>
    </wsdl:message>

    <wsdl:portType name="HistorialPortType">
        <wsdl:operation name="ObtenerHistorialMascota">
            <wsdl:input message="tns:Entrada"/>
            <wsdl:output message="tns:Salida"/>
        </wsdl:operation>
    </wsdl:portType>

    <wsdl:binding
        name="HistorialBinding"
        type="tns:HistorialPortType">

        <soap:binding
            style="document"
            transport="http://schemas.xmlsoap.org/soap/http"/>

        <wsdl:operation name="ObtenerHistorialMascota">
            <soap:operation
                soapAction="{HISTORIAL_NS}/ObtenerHistorialMascota"/>

            <wsdl:input>
                <soap:body use="literal"/>
            </wsdl:input>

            <wsdl:output>
                <soap:body use="literal"/>
            </wsdl:output>
        </wsdl:operation>

    </wsdl:binding>

    <wsdl:service name="HistorialService">
        <wsdl:port
            name="HistorialPort"
            binding="tns:HistorialBinding">

            <soap:address location={direccion_xml}/>
        </wsdl:port>
    </wsdl:service>

</wsdl:definitions>
"""