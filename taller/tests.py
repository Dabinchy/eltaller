from datetime import datetime, timedelta

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from clientes.models import Cliente
from core.models import Sucursal, Usuario

from .models import Tecnico, Turno, Vehiculo


def hora(h, m=0):
    """Fecha fija (mañana) a la hora indicada, en la zona horaria del proyecto."""
    manana = timezone.localdate() + timedelta(days=1)
    return timezone.make_aware(datetime(manana.year, manana.month, manana.day, h, m))


class Base(TestCase):
    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.cliente = Cliente.objects.create(nombre="Piloto Uno")
        self.auto = Vehiculo.objects.create(cliente=self.cliente, patente="ab 123-cd", marca="Ford", modelo="Fiesta")

    def turno(self, inicio, duracion=60, **kw):
        datos = dict(sucursal=self.suc, cliente=self.cliente, vehiculo=self.auto, inicio=inicio, duracion_min=duracion)
        datos.update(kw)
        return Turno.objects.create(**datos)


class VehiculoTests(Base):
    def test_patente_normalizada_y_unica(self):
        self.assertEqual(self.auto.patente, "AB123CD")
        with self.assertRaises(ValidationError):
            Vehiculo.objects.create(cliente=self.cliente, patente="AB 123 CD", marca="X", modelo="Y")

    def test_vin_unico_solo_si_tiene_valor(self):
        Vehiculo.objects.create(cliente=self.cliente, patente="AA111AA", marca="X", modelo="Y")
        Vehiculo.objects.create(cliente=self.cliente, patente="AA222AA", marca="X", modelo="Y", vin="abc-123")
        with self.assertRaises(ValidationError):
            Vehiculo.objects.create(cliente=self.cliente, patente="AA333AA", marca="X", modelo="Y", vin="ABC123")

    def test_km_nunca_baja(self):
        self.auto.registrar_km(15000)
        self.auto.registrar_km(9000)
        self.auto.refresh_from_db()
        self.assertEqual(self.auto.km_actual, 15000)

    def test_en_la_web_requiere_aprobacion(self):
        self.auto.publicado_web = True
        self.assertFalse(self.auto.esta_en_la_web)
        self.auto.aprobado_por_taller = True
        self.assertTrue(self.auto.esta_en_la_web)


class TecnicoTests(Base):
    def test_piloto_no_puede_ser_tecnico(self):
        piloto = Usuario.objects.create_user("piloto", password="x", tipo=Usuario.Tipo.PILOTO)
        with self.assertRaises(ValidationError):
            Tecnico.objects.create(nombre="X", usuario=piloto)

    def test_comision_entre_0_y_100(self):
        with self.assertRaises(ValidationError):
            Tecnico.objects.create(nombre="X", comision_pct=120)


class TurnoTests(Base):
    def test_vehiculo_debe_ser_del_cliente(self):
        otro = Cliente.objects.create(nombre="Otro")
        with self.assertRaises(ValidationError):
            self.turno(hora(10), cliente=otro)

    def test_sin_cupo_no_hay_limite(self):
        for _ in range(10):
            self.turno(hora(10))
        self.assertEqual(Turno.objects.count(), 10)

    def test_cupo_rechaza_el_excedente(self):
        self.suc.cupo_turnos = 2
        self.suc.save()
        self.turno(hora(10))
        self.turno(hora(10, 30))
        with self.assertRaisesMessage(ValidationError, "cupo 2"):
            self.turno(hora(10, 45))

    def test_turno_sin_superposicion_pasa(self):
        self.suc.cupo_turnos = 1
        self.suc.save()
        self.turno(hora(10))          # 10:00 a 11:00
        self.turno(hora(11))          # empieza justo cuando termina el anterior
        self.turno(hora(9), 60)       # termina justo cuando empieza el primero

    def test_cuenta_el_pico_no_la_suma(self):
        # Cupo 2: A (10-10:30) y B (11-12) no coinciden entre sí; el nuevo (10-12) sólo se cruza con uno a la vez.
        self.suc.cupo_turnos = 2
        self.suc.save()
        self.turno(hora(10), 30)
        self.turno(hora(11), 60)
        self.turno(hora(10), 120)

    def test_cancelar_libera_el_lugar(self):
        self.suc.cupo_turnos = 1
        self.suc.save()
        t = self.turno(hora(10))
        with self.assertRaises(ValidationError):
            self.turno(hora(10))
        t.estado = Turno.Estado.CANCELADO
        t.save()
        self.turno(hora(10))

    def test_reactivar_respeta_el_cupo(self):
        self.suc.cupo_turnos = 1
        self.suc.save()
        cancelado = self.turno(hora(10), estado=Turno.Estado.CANCELADO)
        self.turno(hora(10))
        cancelado.estado = Turno.Estado.PENDIENTE
        with self.assertRaises(ValidationError):
            cancelado.save()

    def test_cupo_es_por_sucursal(self):
        self.suc.cupo_turnos = 1
        self.suc.save()
        otra = Sucursal.objects.create(nombre="Norte", cupo_turnos=1)
        self.turno(hora(10))
        self.turno(hora(10), sucursal=otra)


@override_settings(ALLOWED_HOSTS=["testserver"])
class AdminTests(Base):
    def usuario(self, nombre, grupo, **kw):
        u = Usuario.objects.create_user(nombre, password="x", is_staff=True, **kw)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def test_admin_por_rol(self):
        otra = Sucursal.objects.create(nombre="Norte")
        mio = self.turno(hora(10))
        ajeno = self.turno(hora(10), sucursal=otra)
        adm = self.usuario("adm", "administracion", sucursal=self.suc)
        self.client.force_login(adm)
        self.assertEqual(self.client.get(f"/admin/taller/turno/{mio.pk}/change/").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/taller/turno/{ajeno.pk}/change/").status_code, 302)
        self.assertEqual(self.client.get("/admin/taller/vehiculo/add/").status_code, 200)
        self.assertEqual(self.client.get("/admin/taller/tecnico/add/").status_code, 403)

        self.client.force_login(self.usuario("mec", "mecanico"))
        self.assertEqual(self.client.get("/admin/taller/turno/").status_code, 403)

    def test_cupo_lleno_muestra_error_en_el_formulario(self):
        self.suc.cupo_turnos = 1
        self.suc.save()
        self.turno(hora(10))
        self.client.force_login(self.usuario("adm", "administracion", sucursal=self.suc))
        inicio = timezone.localtime(hora(10, 30))
        r = self.client.post("/admin/taller/turno/add/", {
            "sucursal": self.suc.pk, "cliente": self.cliente.pk, "vehiculo": self.auto.pk,
            "inicio_0": inicio.strftime("%d/%m/%Y"), "inicio_1": inicio.strftime("%H:%M:%S"),
            "duracion_min": "60", "motivo": "Service", "estado": "PENDIENTE",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "cupo 1")
        self.assertEqual(Turno.objects.count(), 1)
