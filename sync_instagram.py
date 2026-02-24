import os
import json
import subprocess

def main():
    # Asegurar que instaloader está instalado
    try:
        import instaloader
    except ImportError:
        print("Instalando instaloader...")
        subprocess.check_call(["pip3", "install", "instaloader", "--break-system-packages"])
        import instaloader

    L = instaloader.Instaloader()
    
    # Nombre de usuario a sincronizar
    PROFILE = "mikostudios.co"
    
    print(f"Obteniendo posts de {PROFILE}...")
    try:
        profile = instaloader.Profile.from_username(L.context, PROFILE)
        
        posts_data = []
        # Obtener los ultimos 3 posts
        for post in profile.get_posts():
            posts_data.append({
                "permalink": f"https://www.instagram.com/p/{post.shortcode}/",
                "media_url": post.url
            })
            if len(posts_data) >= 3:
                break
                
        # Guardar en data/instagram.json
        output_file = os.path.join(os.path.dirname(__file__), "data", "instagram.json")
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        with open(output_file, "w") as f:
            json.dump(posts_data, f, indent=2)
            
        print(f"¡Sincronización exitosa! Se guardaron {len(posts_data)} posts en {output_file}")
        
    except Exception as e:
        print("Error durante la sincronización:", e)

if __name__ == "__main__":
    main()
