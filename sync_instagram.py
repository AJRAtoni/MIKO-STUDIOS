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
        import requests
        profile = instaloader.Profile.from_username(L.context, PROFILE)
        
        posts_data = []
        img_dir = os.path.join(os.path.dirname(__file__), "data", "ig_images")
        os.makedirs(img_dir, exist_ok=True)
        
        # Obtener los ultimos 9 posts
        for post in profile.get_posts():
            # Descargar la imagen
            img_path = os.path.join(img_dir, f"{post.shortcode}.jpg")
            if not os.path.exists(img_path):
                img_data = requests.get(post.url).content
                with open(img_path, 'wb') as handler:
                    handler.write(img_data)
                    
            posts_data.append({
                "permalink": f"https://www.instagram.com/p/{post.shortcode}/",
                "media_url": f"./data/ig_images/{post.shortcode}.jpg"
            })
            if len(posts_data) >= 9:
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
