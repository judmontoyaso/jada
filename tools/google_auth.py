"""
tools/google_auth.py
Script de inicialización para obtener permisos OAuth2 de Google Calendar.
Debe ejecutarse manualmente la primera vez en la terminal.
"""
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Permisos para leer y escribir eventos en Google Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')
TOKEN_FILE = os.path.join(os.path.dirname(__file__), '..', 'token.json')

def main():
    creds = None
    
    # Intenta cargar el token si ya existe
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # Si no hay credenciales (o no son válidas), pide iniciar sesión.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refrescando token...")
            creds.refresh(Request())
        else:
            print("Iniciando flujo de autenticación...")
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES)
            
            # Cambiamos puerto a 8090 porque el 8080 puede estar ocupado
            creds = flow.run_local_server(port=8090, access_type='offline', prompt='consent')
        
        # Guarda las credenciales para la próxima ejecución
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            print(f"Token guardado exitosamente en: {TOKEN_FILE}")
            
    print("✅ Autenticación con Google completada con éxito.")

if __name__ == '__main__':
    main()
