# Validación de firewall-app 1.4.1 antes de exámenes

Estado de esta entrega: código y pruebas simuladas revisados; pendiente prueba
piloto en RouterOS 7.21.4 y en el escritorio real. No se ha conectado al CCR.
No se debe anunciar que EXAM/RESTRICTED están validados en producción hasta
completar las pruebas siguientes.

## Hallazgos de la revisión

1. En 1.4.0, la limpieza de conntrack terminaba en el primer DELETE fallido.
   Una entrada que expirase entre GET y DELETE podía dejar el resto sin borrar.
   No existía relectura final. Corregido y reproducido con pruebas.
2. La UI anunciaba el cambio correcto antes de terminar la limpieza y el fallo
   solo quedaba en el registro. Ahora distingue listas y conexiones previas.
3. `remove_address` probaba POST tras errores de DELETE, incluso de conexión.
   El resultado incierto se verifica releyendo, sin otra escritura a ciegas.
4. El controlador podía conservar estado conocido al fallar un cambio. Ahora se
   invalida; la UI también lo invalida y requiere actualizar antes de escribir.
5. Los controles podían habilitarse al aplicar una instantánea SELECTIVE aunque
   siguiera una operación en curso. Ahora el lock cubre la aplicación en Tk.
6. Respuestas REST inesperadas se interpretaban como listas vacías. Ahora fallan
   explícitamente para no deducir NORMAL o una limpieza correcta de datos inválidos.
7. Las consultas sucesivas abrían sesiones HTTP independientes. Se reutiliza una
   sesión y se solicitan solo los campos necesarios de conntrack.

La fotografía revisada mostraba una ventana sin versión y un aviso genérico
manteniendo MODE_EXAM. No coincide con la UI de main 1.4.0. Hay que inventariar
las copias realmente ejecutadas; no basta con actualizar una carpeta distinta.
El error `Errno 101 Network is unreachable` sigue requiriendo diagnosticar rutas
y conectividad del equipo ejecutor: esta actualización no repara una red caída.

## Configuración aportada del CCR: hallazgos confirmados

La revisión del listado aportado el 13/11/2026 confirma:

- La primera regla de `forward` acepta `established,related`, antes de los
  bloques EXAM, RESTRICTED y SELECTIVE. Una conexión ya aceptada no alcanza los
  DROP de esos modos. Con `loose-tcp-tracking=yes`, borrar conntrack tampoco
  garantiza impedir que un flujo TCP se reconstruya y vuelva a ser aceptado.
- No aparece ninguna regla FastTrack en el filtro aportado; RAW está vacío.
  No atribuir este incidente a FastTrack sin nueva evidencia.
- Hay interfaces VLAN de aulas con `l3-hw-offloading=yes` y bandera H, incluida
  la VLAN 210 de la captura. Es necesario comprobar la configuración del chip,
  los puertos y el recorrido hasta la salida: el listado no demuestra por sí
  solo qué conexiones concretas se están encaminando por hardware.
- `active-ipv6=no` en conntrack no demuestra que IPv6 esté deshabilitado en
  todos los clientes ni sustituye la revisión de su política.
- SELECTIVE tiene permisos base para Search-URLs y Google-URLs, además de las
  reglas opcionales. Por tanto, desmarcar ALLOW_SEARCH no revoca necesariamente
  esos destinos. Esto requiere decidir y ajustar la política del CCR; no lo
  corrige el catálogo dinámico de casillas.

No se incluye el volcado completo de la red en este repositorio.

### Orden propuesto para las reglas aportadas

Mantener íntegros, en este orden, los bloques EXAM, RESTRICTED y SELECTIVE
(cada uno con sus excepciones y su DROP final). Situar después la aceptación
general de `established,related`, justo antes del primer permiso NORMAL.
Así, los paquetes originados por una VLAN restringida se evalúan incluso si
pertenecen a una conexión establecida. Las respuestas desde destinos externos
que no pertenezcan a esos modos alcanzan la aceptación de conexiones conocidas.

El siguiente bloque es específico del listado revisado. Revisar que no haya
cambiado, conservar acceso por gestión y activar Safe Mode antes de aplicarlo.
El movimiento afecta a todas las VLAN que estén en modos especiales; no es un
cambio exclusivo de la VLAN piloto. No lo ejecuta la app.

```routeros
{
    :local established [/ip firewall filter find where chain="forward" and action="accept" and connection-state="established,related" and disabled=no]
    :local normal [/ip firewall filter find where chain="forward" and comment="MODE_NORMAL | allow Proxmox from SRC_GENERAL" and disabled=no]
    :if (([:len $established] != 1) or ([:len $normal] != 1)) do={
        :error "No se cambia el orden: revisar reglas y anclas"
    }
    /ip firewall filter move $established destination=$normal
}
/ip firewall filter print detail without-paging
```

Verificar visualmente el orden y probar tráfico nuevo y previamente abierto.
No cambiar `loose-tcp-tracking` globalmente para compensar el orden incorrecto.
No añadir un DROP aislado delante de las excepciones de Aules/identidad.

### Comprobación de L3HW

Recoger primero `/interface ethernet switch print detail` y
`/interface ethernet switch port print detail`. En las VLAN de examen debe
garantizarse el paso por CPU/firewall. RouterOS permite controlar L3HW por VLAN;
una prueba acotada, si la VLAN elegida es la 210 del listado, sería:

```routeros
/interface vlan set [find where name="VLAN-210" and vlan-id=210] l3-hw-offloading=no
/interface vlan print detail where vlan-id=210
```

No desactivar el hardware bridging de todos los switches: es distinto del
encaminamiento L3HW. Revisar rutas y comportamiento tras el cambio; las
conexiones existentes pueden requerir limpieza y nueva prueba. No concluir que
el resto de aulas queda validado por haber probado solo una VLAN.

## Revisión del CCR (solo lectura)

Recoger las reglas completas, incluyendo cadenas auxiliares y su orden:

```routeros
/ip firewall filter print detail without-paging
/ip firewall raw print detail without-paging
/ip firewall mangle print detail without-paging
/ip firewall connection tracking print
/interface vlan print detail
/interface ethernet switch print detail
/interface ethernet switch port print detail
/ipv6 settings print
/ipv6 firewall filter print detail without-paging
/ip dns print
/ip dns static print detail
```

Revisar conjuntamente:

- Los paquetes de EXAM/RESTRICTED deben alcanzar su política antes de reglas
  generales que los acepten o FastTrack. Comprobar también el tráfico de retorno,
  las reglas con `connection-state=new`, los saltos y el orden entre modos.
  No mover una única regla DROP delante de sus propias excepciones: bloquearía
  también Aules/identidad. Preparar el orden completo con las reglas reales.
- Revisar `ALLOW_*` residuales, incluidas las heredadas (la app no borra
  ALLOW_MICROSOFT automáticamente), excepciones por host y redes solapadas.
- FastTrack y L3HW pueden evitar el recorrido esperado por CPU/firewall. No
  confundir la H de hardware bridging en un switch con offload de enrutamiento.
- Una aceptación anticipada de `established,related`, combinada con TCP loose
  tracking, puede aceptar flujos reconstruidos. No cambiar globalmente ese
  ajuste como sustituto de revisar la política completa.
- La app trabaja con IPv4. Si los clientes tienen salida IPv6, revisar la
  política equivalente; IPv4 EXAM no la controla.
- DNS hacia el CCR es tráfico input. El CCR reenvía al BIND9 10.100.22.248 según
  la configuración acordada. Verificar UDP y TCP 53, Aules y todos los dominios
  de redirección/autenticación reales, con caché fría y caliente.
- Un DNS alternativo directo puede evitar la generación de address-lists
  dinámicas en el CCR. Comprobar también DNS seguro del navegador.
- Las listas de IP de GVA no equivalen a permitir únicamente Aules: otros sitios
  pueden compartir IP. Tampoco un ALLOW por IP distingue rutas HTTPS del sitio.

No aplicar cambios globales de firewall, offload, conntrack o DNS sin revisar
estas salidas. La aplicación no los modifica.

## Actualización uniforme

1. Identificar el script/carpeta que abre cada acceso directo y cerrar las
   instancias antiguas antes de sustituir archivos. Guardar la configuración
   específica de cada aula (VLAN, red, nombre, usuario y endpoint).
2. Tras revisar y aprobar la PR, instalar el mismo commit aprobado en todos los
   equipos. No copiar solo app.py: actualizar también mikrotik_api.py y
   vlan_controller.py. Revisar primero cambios locales; no usar reset --hard.
3. En la carpeta instalada, ejecutar:

   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python app.py --version
   git rev-parse HEAD
   git status --short
   ```

   Se espera `firewall-app 1.4.1`. Registrar el commit y cualquier modificación
   local. La primera línea del registro GUI muestra versión y ruta ejecutada.
4. Probar inicialmente una sola VLAN sin examen en curso. El operador debe
   conservar acceso independiente al CCR por gestión.

La sesión REST no hereda HTTP_PROXY/HTTPS_PROXY ni credenciales de netrc. Si
algún despliegue dependía de un proxy, revisar su conectividad directa antes.
Se mantiene la opción `--verify-ssl`; no se cambia el certificado del router.

## Matriz de aceptación piloto

Usar dos clientes: uno con conexiones abiertas en NORMAL y otro recién iniciado
o sin caché DNS. Probar TCP largo (descarga/stream), HTTPS nuevo y UDP/QUIC. Una
página ya dibujada o en caché no demuestra tráfico: comprobar nuevos bytes y
solicitudes sin caché.

| Prueba | Resultado requerido |
| --- | --- |
| NORMAL → EXAM con conexiones abiertas hacia destinos no permitidos | Se corta el tráfico previo y falla una conexión nueva al mismo destino |
| NORMAL → RESTRICTED con conexiones abiertas | Igual, manteniendo únicamente las excepciones acordadas para RESTRICTED |
| Repetir EXAM o RESTRICTED | Se limpia y verifica otra instantánea sin cambiar a NORMAL |
| EXAM ↔ RESTRICTED | Aules/identidad siguen accesibles; el servicio interno permitido solo en RESTRICTED sigue la política |
| Aules e identidad con caché fría/caliente | Carga completa, redirecciones y login correctos |
| Segunda VLAN en NORMAL | No se borran sus conexiones ni se cambian sus listas |
| Fallo simulado de permisos/borrado en entorno de pruebas | Aviso de limpieza incompleta; no anuncia corte garantizado ni vuelve a NORMAL |
| Pérdida de conexión de la app | Estado desconocido y escrituras deshabilitadas hasta actualizar |
| Reintentar limpieza | No modifica listas; verifica el modo y las conexiones previas |
| Volver a NORMAL | SRC_GENERAL presente, sin modos especiales; navegación recuperada |

Registrar VLAN, cliente, versión/commit de la app, versión RouterOS, hora, modos,
resultado de limpieza, destino probado y resultado de tráfico. Evitar usar Torch
o sniffer como única prueba de FastTrack: pueden alterar la vía rápida y ocultar
el fallo que se quiere reproducir. Comparar también con esas herramientas paradas.

## Alcance de la limpieza

Se seleccionan las entradas cuya dirección original o de respuesta (NAT), en
cualquiera de los dos sentidos, pertenezca a la red gestionada. Se excluye TCP
con destino a la IP/puerto REST configurados para preservar el control desde la
propia aula. Se verifica la desaparición de los IDs de la instantánea inicial;
el contador incluye bajas por expiración natural. No se borran deliberadamente
los IDs nuevos que aparezcan después: pueden ser DNS o tráfico permitido.

La verificación no equivale a enviar TCP RST a los extremos, ni a comprobar las
reglas del router, ni a cerrar sesiones de aplicación en el servidor remoto.
Las llamadas REST no forman una transacción atómica y los IDs pueden cambiar.
No existe lock entre procesos/equipos/WinBox: usar un único operador por VLAN.
Una transición fallida puede dejar dos modos; actualizar y revisar antes de
retirar ninguno. No hay rollback automático que amplíe permisos.

## Pruebas automatizadas

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
```

Los tests de UI usan widgets y cola de callbacks simulados. Requieren tkinter
instalado; pytest los omite si no está disponible. No son una prueba visual de
Tk ni de latencia, ACL, FastTrack, hardware o DNS del CCR real.

## Fuentes técnicas

- [REST API: DELETE, 404 y .proplist](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST%20API)
- [Bloqueo de conexiones abiertas](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/firewall/filter/#block-a-connection-that-is-already-open)
- [Connection tracking y FastTrack](https://help.mikrotik.com/docs/spaces/ROS/pages/130220087/Connection%2Btracking)
- [L3 Hardware Offloading](https://help.mikrotik.com/docs/spaces/ROS/pages/62390319/L3%2BHardware%2BOffloading)
