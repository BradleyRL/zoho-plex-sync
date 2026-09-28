import sys
from config import config
from plexapi.myplex import MyPlexAccount

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 check_user_libraries.py <email_del_usuario>")
        return
        
    email = sys.argv[1].strip().lower()
    
    if not config.PLEX_TOKEN:
        print("Error: PLEX_TOKEN falta en .env")
        return
        
    print("Conectando a Plex...")
    account = MyPlexAccount(token=config.PLEX_TOKEN)
    
    target_user = None
    for u in account.users():
        if (getattr(u, 'email', '') or '').lower() == email or \
           (getattr(u, 'username', '') or '').lower() == email or \
           (getattr(u, 'title', '') or '').lower() == email:
            target_user = u
            break
            
    if not target_user:
        print(f"Usuario '{email}' no encontrado en la lista de amigos.")
        return
        
    print(f"Usuario encontrado: {getattr(target_user, 'title', 'Unknown')} ({getattr(target_user, 'email', 'Unknown')})")
    
    servers = getattr(target_user, 'servers', [])
    if not servers:
        print("El usuario tiene 0 servidores compartidos. (No tiene acceso a ninguna librería)")
        return
        
    print(f"\nEl usuario tiene acceso a {len(servers)} servidor(es).")
    
    for s in servers:
        print(f"\n--- Servidor: {getattr(s, 'name', 'Unknown')} (Share ID: {getattr(s, 'id', '')}, MachineID: {getattr(s, 'machineIdentifier', '')}) ---")
        all_libraries = getattr(s, 'allLibraries', False)
        print(f"¿Tiene acceso a TODAS las librerías automáticamente? {all_libraries}")
        
        sections = getattr(s, 'sections', [])
        if callable(sections):
            sections = sections()
            
        print(f"Número de librerías específicas compartidas: {len(sections)}")
        for sec in sections:
            print(f" - {getattr(sec, 'title', 'Unknown')} (ID: {getattr(sec, 'id', 'Unknown')})")
            
    print("\nComprobación finalizada.")

if __name__ == '__main__':
    main()
