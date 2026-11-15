from django.test import TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["testserver"])
class SitioTests(TestCase):
    def test_paginas_publicas_sin_ingresar(self):
        for url in ("/", "/servicios/", "/contacto/", "/pilotos/", "/pilotos/juan-perez/", "/autos/ford-falcon/",
                    "/campeonatos/", "/campeonatos/tc-2026/", "/asociaciones/pista-norte/",
                    "/publicaciones/", "/publicaciones/nota/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_boton_ingresar(self):
        r = self.client.get("/")
        self.assertContains(r, 'href="/ingresar/"')
        self.assertContains(r, "el-taller.jpg")

    def test_las_areas_no_quedan_tapadas(self):
        self.assertRedirects(self.client.get("/panel/"), "/ingresar/?next=/panel/")
        self.assertEqual(self.client.get("/ingresar/").status_code, 200)
