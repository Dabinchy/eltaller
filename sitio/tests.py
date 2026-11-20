from django.test import TestCase, override_settings

from . import partes


@override_settings(ALLOWED_HOSTS=["testserver"])
class SitioTests(TestCase):
    def test_paginas_publicas_sin_ingresar(self):
        for url in (
            # El Taller
            "/", "/servicios/", "/trabajos/", "/presupuesto/", "/contacto/",
            # El Prepa
            "/prepa/", "/prepa/competicion/", "/prepa/personalizacion/", "/prepa/clasicos/",
            "/prepa/proyectos/", "/prepa/proyectos/falcon-72/", "/prepa/consulta/",
            # Campeonatos
            "/campeonatos/", "/pilotos/", "/asociaciones/",
            # Compartido
            "/publicaciones/", "/publicaciones/nota/",
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        # Lo que no existe (o no es público) da 404
        for url in ("/campeonatos/tc-2026/", "/pilotos/juan-perez/", "/autos/ford-falcon/",
                    "/asociaciones/pista-norte/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_parte_segun_direccion(self):
        self.assertEqual(partes.parte_de_ruta("/"), partes.TALLER)
        self.assertEqual(partes.parte_de_ruta("/servicios/"), partes.TALLER)
        self.assertEqual(partes.parte_de_ruta("/publicaciones/nota/"), partes.TALLER)
        self.assertEqual(partes.parte_de_ruta("/prepa/clasicos/"), partes.PREPA)
        for ruta in ("/campeonatos/", "/pilotos/x/", "/autos/x/", "/asociaciones/x/"):
            self.assertEqual(partes.parte_de_ruta(ruta), partes.CAMPEONATOS, ruta)

    def test_encabezado_de_cada_parte(self):
        r = self.client.get("/")
        self.assertContains(r, 'data-parte="taller"')
        self.assertContains(r, "el-taller.png")
        self.assertContains(r, 'href="/ingresar/?parte=taller"')
        self.assertContains(r, "Pedir presupuesto")
        # Las tres pestañas en todas las páginas
        for url in ("/prepa/", "/campeonatos/"):
            self.assertContains(r, f'href="{url}"')

        r = self.client.get("/prepa/clasicos/")
        self.assertContains(r, '<body class="cc-app sitio d-flex flex-column min-vh-100" data-parte="prepa">')
        self.assertContains(r, "el-prepa.png")
        self.assertContains(r, 'href="/ingresar/?parte=prepa"')
        self.assertContains(r, 'aria-current="page"')   # "Clásicos" marcado en el menú

        r = self.client.get("/pilotos/")
        self.assertContains(r, 'data-parte="campeonatos">')
        self.assertContains(r, 'href="/ingresar/?parte=campeonatos"')
        self.assertContains(r, "Acceso pilotos")
        self.assertNotContains(r, "Pedir presupuesto")

    def test_ingreso_con_la_marca_de_la_parte(self):
        r = self.client.get("/ingresar/?parte=campeonatos")
        self.assertContains(r, "Acceso pilotos")
        self.assertContains(r, "campeonatos.svg")
        self.assertContains(r, 'name="parte" value="campeonatos"')
        r = self.client.get("/ingresar/?parte=prepa")
        self.assertContains(r, "el-prepa.png")
        # Sin parte (o una inválida): ingreso general con la marca El Taller
        for url in ("/ingresar/", "/ingresar/?parte=otra"):
            r = self.client.get(url)
            self.assertContains(r, "el-taller.png")
        self.assertContains(self.client.get("/ingresar/"), "Personal del taller, pilotos y clientes")

    def test_las_areas_no_quedan_tapadas(self):
        self.assertRedirects(self.client.get("/panel/"), "/ingresar/?next=/panel/")
        self.assertEqual(self.client.get("/ingresar/").status_code, 200)
